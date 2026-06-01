# ARG instructions used in FROM must come before the FROM instruction
ARG UBUNTU_VERSION=24.04
FROM ubuntu:${UBUNTU_VERSION}

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install core dependencies
RUN apt-get update && apt-get install -y \
    curl \
    iproute2 \
    wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

#========================================
# setup nordvon client
#========================================
ARG NORDVPN_VERSION=1.0.0
COPY files/nordvpn-release_${NORDVPN_VERSION}_all.deb /tmp/nordvpn.deb

# Download and install from the corrected NordVPN repository structural path
RUN apt-get update \
    && apt-get install -y /tmp/nordvpn.deb \
    && rm -rf /tmp/nordvpn.deb

# Install the actual NordVPN CLI client
RUN apt-get update && apt-get install -y \
    nordvpn \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Execute the script on startup
ENTRYPOINT ["/entrypoint.sh"]
