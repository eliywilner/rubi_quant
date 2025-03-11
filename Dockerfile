### Dockerfile for IB Gateway ###

# Use Ubuntu as the base image (force x86_64 for AWS & Mac M1/M2)
FROM --platform=linux/amd64 ubuntu:22.04

# Set environment variables for IB Gateway download
ENV IBDOWNLOAD=https://download.interactivebrokers.com/installers/ibgateway

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget xvfb unzip libxtst6 libxrender1 libxi6 qemu-user-static \
    && rm -rf /var/lib/apt/lists/*

# Install IB Gateway (latest stable version)
RUN wget -O /opt/ibgateway-installer.sh \
    "$IBDOWNLOAD/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"

COPY ibgateway-response.txt /opt/ibgateway-response.txt

# RUN chmod +x /opt/ibgateway-installer.sh && \
#     (echo "/root/Jts/ibgateway/1030"; echo "y"; echo "y") | /opt/ibgateway-installer.sh --mode unattended --prefix /root/Jts/ibgateway
ENV INSTALL_PATH="/root/Jts/ibgateway/1030"

RUN chmod +x /opt/ibgateway-installer.sh && \
    echo -e "$INSTALL_PATH\ny" | /opt/ibgateway-installer.sh --mode unattended --prefix "$INSTALL_PATH" && \
    ls -l "$INSTALL_PATH"


# Copy IB Gateway config file for auto-login
COPY ibgateway.xml /root/Jts/ibgateway.xml


# Expose IB Gateway API port
EXPOSE 4002

# Start IB Gateway in headless mode
CMD ["/opt/ibgateway/ibgateway", "start"]
