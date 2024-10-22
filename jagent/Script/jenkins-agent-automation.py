import requests
import argparse
import logging
import sys
import json
import platform
import subprocess
import os
import smtplib
from requests.auth import HTTPBasicAuth
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import time

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(filename='jenkins_agent_creation.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Jenkins agent creation script")
    parser.add_argument('--jenkins_url', required=True, help="Jenkins URL (e.g., http://jenkins-server:8080)")
    parser.add_argument('--username', required=True, help="Username for Jenkins API authentication")
    parser.add_argument('--api_token', required=True, help="API token for Jenkins API authentication")
    parser.add_argument('--agent_name', required=True, help="Name of the Jenkins agent")
    parser.add_argument('--remote_fs', required=True, help="Remote file system path for the agent")
    parser.add_argument('--label', default="", help="Labels assigned to the agent (optional)")
    parser.add_argument('--executors', type=int, default=1, help="Number of executors for the agent (optional)")
    parser.add_argument('--config_file', required=True, help="Path to the JSON configuration file")
    return parser.parse_args()

def get_headers(csrf_token=None):
    """Return headers for Jenkins API requests, including CSRF token if provided."""
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    if csrf_token:
        headers[csrf_token[0]] = csrf_token[1]  # Add CSRF token
    return headers

def get_csrf_token(jenkins_url, auth):
    """Retrieve CSRF token from Jenkins."""
    try:
        crumb_issuer_url = f"{jenkins_url}/crumbIssuer/api/json"
        response = requests.get(crumb_issuer_url, auth=auth)
        response.raise_for_status()  # Check for errors
        crumb_data = response.json()
        return crumb_data['crumbRequestField'], crumb_data['crumb']  # Return CSRF token name and value
    except requests.exceptions.RequestException as e:
        logging.error(f"Error retrieving CSRF token: {e}")
        raise SystemExit(f"Error retrieving CSRF token: {e}")

def check_agent_exists(jenkins_url, agent_name, headers, auth):
    """Check if the Jenkins agent already exists."""
    check_agent_url = f"{jenkins_url}/computer/{agent_name}/api/json"
    try:
        response = requests.get(check_agent_url, headers=headers, auth=auth)
        if response.status_code == 200:
            logging.info(f"Agent '{agent_name}' already exists.")
            print(f"Agent '{agent_name}' already exists.")
            return True
        elif response.status_code == 404:
            logging.info(f"Agent '{agent_name}' does not exist. Proceeding with creation.")
            return False
        else:
            logging.error(f"Unexpected response while checking agent existence. Status code: {response.status_code}")
            raise SystemExit(f"Error: Unexpected response code {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error checking if agent exists: {e}")
        raise SystemExit(f"Error checking if agent exists: {e}")

def send_email(subject, body):
    """Send an email alert."""
    email_from = os.getenv('EMAIL_FROM')
    email_to = os.getenv('EMAIL_TO')
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = int(os.getenv('SMTP_PORT'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')

    msg = MIMEMultipart()
    msg['From'] = email_from
    msg['To'] = email_to
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, email_to, msg.as_string())
        server.quit()
        print(f"Alert email sent to {email_to}")
    except Exception as e:
        logging.error(f"Failed to send email alert: {e}")
        raise SystemExit(f"Error sending email: {e}")

def monitor_service(agent_name):
    """Continuously monitor Jenkins agent service and send email if service fails."""
    current_platform = platform.system()
    service_status_cmd = []

    if current_platform == "Linux":
        service_status_cmd = ["systemctl", "is-active", f"{agent_name}.service"]
    elif current_platform == "Windows":
        service_status_cmd = ["sc", "query", agent_name]

    try:
        while True:
            result = subprocess.run(service_status_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode != 0:
                subject = f"Service Failure: {agent_name}"
                body = f"The Jenkins agent service '{agent_name}' has failed or stopped unexpectedly."
                send_email(subject, body)
            else:
                logging.info(f"The Jenkins agent service '{agent_name}' is running normally.")
                print(f"The Jenkins agent service '{agent_name}' is running normally.")
            
            time.sleep(20)  # Wait for the specified interval before checking again
    except Exception as e:
        logging.error(f"Failed to monitor the service: {e}")
        raise SystemExit(f"Error monitoring service: {e}")

# def monitor_service(agent_name):
#     """Monitor Jenkins agent service and send email if service fails."""
#     current_platform = platform.system()
#     service_status_cmd = []

#     if current_platform == "Linux":
#         service_status_cmd = ["systemctl", "is-active", f"{agent_name}.service"]
#     elif current_platform == "Windows":
#         service_status_cmd = ["sc", "query", agent_name]

#     try:
#         result = subprocess.run(service_status_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#         print(result.returncode)
#         if result.returncode != 0:
#             subject = f"Service Failure: {agent_name}"
#             body = f"The Jenkins agent service '{agent_name}' has failed or stopped unexpectedly."
#             send_email(subject, body)
#         else:
#             logging.info(f"The Jenkins agent service '{agent_name}' is running normally.")
#     except Exception as e:
#         logging.error(f"Failed to monitor the service: {e}")
#         raise SystemExit(f"Error monitoring service: {e}")

def create_agent(jenkins_url, agent_name, headers, auth, remote_fs, label):
    """Create a new Jenkins agent."""
    create_agent_url = f"{jenkins_url}/computer/doCreateItem"
    
    data = {
        'name': agent_name,
        'type': 'hudson.slaves.DumbSlave',
        'json': json.dumps({
            'name': agent_name,
            'nodeDescription': 'Created by REST API',
            'numExecutors': 1,
            'remoteFS': remote_fs,
            'labelString': label,
            'mode': 'NORMAL',
            'retentionStrategy': {'stapler-class': 'hudson.slaves.RetentionStrategy$Always'},
            'launcher': {
                'stapler-class': 'hudson.slaves.JNLPLauncher',
                'workDirSettings': {
                    'disabled': False,
                    'internalDir': 'remoting',
                    'failIfWorkDirIsMissing': False
                }
            },
            'nodeProperties': {'stapler-class-bag': 'true'}
        })
    }

    try:
        response = requests.post(create_agent_url, headers=headers, data=data, auth=auth)
        response.raise_for_status()
        if response.status_code == 200:
            logging.info(f"Agent '{agent_name}' created successfully.")
            print(f"Agent '{agent_name}' created successfully!")
        else:
            logging.error(f"Failed to create agent. Status code: {response.status_code}, Message: {response.text}")
            raise SystemExit(f"Error: Failed to create agent. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Error creating agent: {e}")
        raise SystemExit(f"Error creating agent: {e}")

def download_agent_jar(jenkins_url, remote_fs):
    """Download the Jenkins agent jar file from the Jenkins master."""
    jar_url = f"{jenkins_url}/jnlpJars/agent.jar"
    jar_path = os.path.join(remote_fs, "agent.jar")

    # Ensure the remote_fs directory exists, if not, create it
    if not os.path.exists(remote_fs):
        try:
            os.makedirs(remote_fs)
            print(f"Directory {remote_fs} created.")
        except OSError as e:
            logging.error(f"Error creating directory {remote_fs}: {e}")
            raise SystemExit(f"Error creating directory {remote_fs}: {e}")

    try:
        response = requests.get(jar_url)
        response.raise_for_status()  # Check for errors

        # Save the jar file
        with open(jar_path, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded agent.jar to {jar_path}")
        return jar_path
    except requests.exceptions.RequestException as e:
        logging.error(f"Error downloading agent.jar: {e}")
        raise SystemExit(f"Error downloading agent.jar: {e}")

def install_agent_service(agent_name, jenkins_url, remote_fs, username, api_token):
    """Install Jenkins agent as a service based on the platform."""
    current_platform = platform.system()

    # Download the agent.jar
    jar_path = download_agent_jar(jenkins_url, remote_fs)

    if current_platform == "Linux":
        # Create a systemd service for Linux
        create_linux_service(agent_name, jenkins_url, username, api_token, jar_path, remote_fs)
    elif current_platform == "Windows":
        # Use NSSM for Windows
        create_windows_service(agent_name, jenkins_url, username, api_token, jar_path, remote_fs)
    else:
        raise SystemExit(f"Unsupported platform: {current_platform}")

def create_linux_service(agent_name, jenkins_url, username, api_token, jar_path, work_dir):
    """Create a systemd service for the Jenkins agent on Linux using username and api_token."""
    
    # Ensure jenkins_url does not end with a trailing slash to avoid issues
    if jenkins_url.endswith('/'):
        jenkins_url = jenkins_url[:-1]
    print(f"/usr/bin/java -jar {jar_path} -jnlpUrl {jenkins_url}/computer/{agent_name}/jenkins-agent.jnlp -jnlpCredentials {username}:{api_token} -workDir {work_dir}")
    
    service_content = f"""
[Unit]
Description=Jenkins Agent for {agent_name}
After=network.target

[Service]
ExecStart=/usr/bin/java -jar {jar_path} -jnlpUrl {jenkins_url}/computer/{agent_name}/jenkins-agent.jnlp -jnlpCredentials {username}:{api_token} -workDir {work_dir}
User=gopal
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""
    service_file_path = f"/etc/systemd/system/{agent_name}.service"
    
    try:
        # Write the systemd service file
        with open(service_file_path, 'w') as service_file:
            service_file.write(service_content)

        # Reload systemd, enable, and start the service
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", f"{agent_name}.service"], check=True)
        subprocess.run(["systemctl", "start", f"{agent_name}.service"], check=True)
        print(f"Jenkins agent '{agent_name}' installed as a Linux service.")
    except Exception as e:
        raise SystemExit(f"Failed to create and start the systemd service: {e}")

def create_windows_service(agent_name, jenkins_url, username, api_token, jar_path, work_dir):
    """Create a Windows service for the Jenkins agent using NSSM and JNLP credentials."""
    service_name = f"{agent_name}_service"
    nssm_path = "C:\\path\\to\\nssm.exe"  # Update to your NSSM path
    
    try:
        # Install and start the Windows service using NSSM
        subprocess.run([nssm_path, "install", service_name, "java", "-jar", jar_path, 
                        "-jnlpUrl", f"{jenkins_url}/computer/{agent_name}/jenkins-agent.jnlp", 
                        "-jnlpCredentials", f"{username}:{api_token}", 
                        "-workDir", work_dir], check=True)
        subprocess.run([nssm_path, "start", service_name], check=True)
        print(f"Jenkins agent '{agent_name}' installed as a Windows service.")
    except Exception as e:
        raise SystemExit(f"Failed to create and start the Windows service: {e}")

def main():
    """Main entry point for the script."""
    try:
        args = parse_arguments()
        auth = HTTPBasicAuth(args.username, args.api_token)  # Basic Authentication

        # Step 1: Retrieve CSRF token
        csrf_token = get_csrf_token(args.jenkins_url, auth)  # Get CSRF token

        # Update headers to include the CSRF token
        headers = get_headers(csrf_token)  # Include CSRF token in headers

        # Step 2: Check if the agent already exists
        if not check_agent_exists(args.jenkins_url, args.agent_name, headers, auth):
            # Step 3: Create the agent if it doesn't exist
            create_agent(args.jenkins_url, args.agent_name, headers, auth, args.remote_fs, args.label)

        # Step 4: Download the agent.jar and install Jenkins agent as a service using the username and api_token
        install_agent_service(args.agent_name, args.jenkins_url, args.remote_fs, args.username, args.api_token)

        # Step 5: Monitor the service and send an email if it fails

        monitor_service(args.agent_name)

        print("line 283")

    except KeyboardInterrupt:
        logging.error("Script interrupted by user.")
        sys.exit(1)

if __name__ == "__main__":
    main()