#!/bin/bash
set -e

# 1. Ensure a token was provided
if [ -z "$TOKEN" ]; then
    echo "ERROR: The 'TOKEN' environment variable is not set." >&2
    exit 1
fi

# 2. Start the background NordVPN daemon
echo "Starting NordVPN daemon..."
/usr/sbin/nordvpnd > /dev/null 2>&1 &

# Wait for the daemon to fully spin up
until nordvpn status > /dev/null 2>&1; do
    sleep 0.5
done

# 3. Authenticate and configure the client
echo "Logging into NordVPN..."
nordvpn login --token "$TOKEN" > /dev/null

echo "Switching protocol to NordLynx (WireGuard)..."
nordvpn set technology nordlynx > /dev/null

# 4. Connect to force key provisioning
echo "Connecting to establish handshake..."
nordvpn connect > /dev/null

# 5. Extract the key using the WireGuard tool
echo "------------------------------------------------"
echo "YOUR NORDLYNX PRIVATE KEY:"
echo "------------------------------------------------"
wg show nordlynx private-key
echo "------------------------------------------------"

# 6. Clean up and disconnect
nordvpn disconnect > /dev/null
