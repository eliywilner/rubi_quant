### install.sh - Automated EC2 Setup for Running RubiQuant ###

#!/bin/bash
set -e  # Exit script on any error

# Update and install dependencies without prompts
sudo apt update -y && sudo apt upgrade -y
sudo apt install -y docker.io git unzip wget xvfb libxtst6 libxrender1 libxi6 python3 python3-pip

# Start Docker and enable it on boot
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ubuntu  # Allow 'ubuntu' user to run Docker without sudo

# Logout and log back in to apply Docker permissions
echo "Installation complete. Please log out and log back in to apply changes."

# Build and run the latest RubiQuant Docker image
cd /home/ubuntu/rubi_quant  # Assuming repo is cloned here
sudo docker build --platform=linux/amd64 -t rubi_quant .
sudo docker run -d --name rubi_quant_container \
    --env-file .env -p 4002:4002 rubi_quant
