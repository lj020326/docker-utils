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

# Wait for the status to switch to Connected (max 10 seconds)
# This prevents the race condition where the interface is up but the status info isn't populated
printf "Waiting for endpoint status negotiation..."
RETRY=0
while ! nordvpn status | grep -q "Status: Connected" && [ $RETRY -lt 20 ]; do
    sleep 0.5
    printf "."
    RETRY=$((RETRY+1))
done
echo ""

# Extract the connected endpoint server from status
#nordvpn status
ENDPOINT_SERVER=$(nordvpn status | grep -i "Hostname" | awk -F': ' '{print $2}')
if [ -z "$ENDPOINT_SERVER" ]; then
    ENDPOINT_SERVER="Unknown (Failed to retrieve status)"
fi

# Extract the WireGuard interface IP address
INTERFACE_IP=$(ip -o -4 addr show dev nordlynx 2>/dev/null | awk '{print $4}' || echo "10.5.0.2/16")

# Extract the WireGuard private key
PRIV_KEY=$(wg show nordlynx private-key 2>/dev/null)

# Display the comprehensive output block
echo "############################################################"
echo "Endpoint Server: $ENDPOINT_SERVER"
echo "IP:              $INTERFACE_IP"
echo "Private Key:     $PRIV_KEY"
echo "############################################################"

nordvpn disconnect > /dev/null
