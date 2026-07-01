# NordVPN WireGuard Key Extractor

A minimalist Docker utility designed to extract your official NordVPN WireGuard (`NordLynx`) private key, client interface IP, and the active connected endpoint server.

Because NordVPN's API requires request signatures that make basic `curl` methods throw `400 Bad Request` errors, this project uses the official NordVPN Linux client wrapped inside a lightweight container to cleanly handle authentication, provision the link, output the private key, and immediately self-destruct.

## Prerequisites

* **Docker** installed and running on your host machine.
* A **NordVPN Access Token**. You can generate one by logging into the [NordAccount Dashboard](https://my.nordaccount.com/), navigating to **NordVPN**, scrolling down to **Access Tokens**, and clicking **Generate Token**.

## Project Structure

Ensure your local directory contains the following files:

```text
.
├── Dockerfile
├── README.md
└── entrypoint.sh
```

---

## Configuration Files

### 1. `entrypoint.sh`
This script coordinates starting the NordVPN daemon, logging in, changing the technology protocol to NordLynx, forcing a connection to generate the keys, and dumping the private key string to standard output.

```bash
#!/bin/bash
set -e

if [ -z "$TOKEN" ]; then
    echo "ERROR: The 'TOKEN' environment variable is not set." >&2
    exit 1
fi

echo "Starting NordVPN daemon..."
/usr/sbin/nordvpnd > /dev/null 2>&1 &

until nordvpn status > /dev/null 2>&1; do
    sleep 0.5
done

echo "Logging into NordVPN..."
nordvpn login --token "$TOKEN" > /dev/null

echo "Switching protocol to NordLynx (WireGuard)..."
nordvpn set technology nordlynx > /dev/null

echo "Connecting to establish handshake..."
nordvpn connect > /dev/null

printf "Waiting for endpoint status negotiation..."
RETRY=0
while ! nordvpn status | grep -q "Status: Connected" && [ $RETRY -lt 20 ]; do
    sleep 0.5
    printf "."
    RETRY=$((RETRY+1))
done
echo ""

ENDPOINT_SERVER=$(nordvpn status | grep -i "Current server" | awk -F': ' '{print $2}')
if [ -z "$ENDPOINT_SERVER" ]; then
    ENDPOINT_SERVER="Unknown"
fi

INTERFACE_IP=$(ip -o -4 addr show dev nordlynx 2>/dev/null | awk '{print $4}' || echo "10.5.0.2/16")
PRIV_KEY=$(wg show nordlynx private-key 2>/dev/null)

echo "############################################################"
echo "Endpoint Server: $ENDPOINT_SERVER"
echo "IP:              $INTERFACE_IP"
echo "Private Key:     $PRIV_KEY"
echo "############################################################"

nordvpn disconnect > /dev/null
```

### 2. `Dockerfile`
```dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl \
    iproute2 \
    wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSf [https://repo.nordvpn.com/deb/nordvpn/debian/pool/main/n/nordvpn-release/nordvpn-release_1.0.0_all.deb](https://repo.nordvpn.com/deb/nordvpn/debian/pool/main/n/nordvpn-release/nordvpn-release_1.0.0_all.deb) -o /tmp/nordvpn.deb \
    && apt-get update \
    && apt-get install -y /tmp/nordvpn.deb \
    && rm -rf /tmp/nordvpn.deb

RUN apt-get update && apt-get install -y \
    nordvpn \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

---

## Usage Instructions

### 1. Set File Permissions
Ensure the entrypoint script has execution rights on your host machine before building the image:
```bash
chmod +x entrypoint.sh
```

### 2. Build the Docker Image
Compile the custom container tool using standard Docker build syntax:
```bash
docker build -t local/nord-key-extractor .
## OR if building from the repo root
docker build -t local/nord-key-extractor -f image/nord-key-extractor/Dockerfile image/nord-key-extractor
```

### 3. Run the Container
Run the container by passing your personal NordVPN access token into the environment variables. 

> ⚠️ **Important:** You **must** include the `--cap-add=NET_ADMIN` flag. Without this capability constraint added, the container cannot provision the internal virtual network interface needed to trigger the cryptographic handshake.

```bash
NORDVPN_TOKEN=token_value_here
docker run --rm --cap-add=NET_ADMIN -e TOKEN=$NORDVPN_TOKEN local/nord-key-extractor
```

### Expected Output
The process takes roughly 5–10 seconds to execute. Once completed, your console will show:

```text
Starting NordVPN daemon...
Logging into NordVPN...
Switching protocol to NordLynx (WireGuard)...
Connecting to establish handshake...
Waiting for endpoint status negotiation......
############################################################
Endpoint Server: us10023.nordvpn.com
IP:              10.5.0.2/16
Private Key:     gK3Xy...[44-character-string-ending-in-=]...=
############################################################
```

Because the `--rm` flag is used, the container automatically wipes its filesystem stack from your Docker engine the instant it finishes printing the key string.
