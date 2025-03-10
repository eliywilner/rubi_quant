### Updated Dockerfile for IB Gateway (macOS + AWS Compatible) ###

# Use Ubuntu as the base image (forcing x86_64 for Mac M1/M2 compatibility)
FROM --platform=linux/amd64 ubuntu:22.04

# Set environment variables for IB Gateway download
ENV IBDOWNLOAD=https://download.interactivebrokers.com/installers/ibgateway

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget xvfb unzip libxtst6 libxrender1 libxi6 \
    qemu-user-static \
    && rm -rf /var/lib/apt/lists/*

# Download and install the stable IB Gateway version
RUN wget -O /opt/ibgateway-installer.sh \
    "$IBDOWNLOAD/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"

# Make the installer executable and run it in unattended mode
RUN chmod +x /opt/ibgateway-installer.sh && \
    /opt/ibgateway-installer.sh --mode unattended --prefix /opt/ibgateway

# Copy IB Gateway config file for auto-login
COPY ibgateway.xml /root/Jts/ibgateway.xml

# Set up environment variables for login
ENV IBKR_USERNAME=""
ENV IBKR_PASSWORD=""
ENV TWS_API_PORT=4002

# Expose IB Gateway API port
EXPOSE 4002

# Start IB Gateway in headless mode with x86_64 emulation for Apple Silicon
ENTRYPOINT ["/opt/ibgateway/ibgateway", "start"]
