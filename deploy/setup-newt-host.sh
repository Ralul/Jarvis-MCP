#!/usr/bin/env bash
# =============================================================================
# setup-newt-host.sh — Install host-level Newt (Pangolin client)
# =============================================================================
# Runs Newt directly on the host OS (not in Kubernetes) so SSH access
# works even if MicroK8s is down.
#
# Usage:
#   sudo bash setup-newt-host.sh
#
# After running:
#   1. Edit /opt/newt-host/newt.env with your Pangolin credentials
#   2. sudo systemctl start newt-host
#   3. In Pangolin dashboard: add TCP resource → target 127.0.0.1:22
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEWT_VERSION="1.19.0"
NEWT_URL="https://github.com/fosrl/newt/releases/download/${NEWT_VERSION}/newt_linux_amd64"
INSTALL_DIR="/opt/newt-host"

echo "=== Installing host-level Newt (Pangolin client) ==="

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  NEWT_ASSET="newt_linux_amd64" ;;
    aarch64) NEWT_ASSET="newt_linux_arm64" ;;
    armv7l)  NEWT_ASSET="newt_linux_arm32" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac
NEWT_URL="https://github.com/fosrl/newt/releases/download/${NEWT_VERSION}/${NEWT_ASSET}"

# Create directory
mkdir -p "$INSTALL_DIR"

# Download Newt binary
echo "Downloading Newt ${NEWT_VERSION} (${NEWT_ASSET})..."
curl -sL -o /tmp/newt "$NEWT_URL"
chmod +x /tmp/newt
mv /tmp/newt "$INSTALL_DIR/newt"
echo "Newt installed: $INSTALL_DIR/newt ($($INSTALL_DIR/newt --help 2>&1 | head -1 || echo 'binary ready'))"

# Create env file from template
if [ ! -f "$INSTALL_DIR/newt.env" ]; then
    cp "$SCRIPT_DIR/newt-host.env.example" "$INSTALL_DIR/newt.env"
    chmod 600 "$INSTALL_DIR/newt.env"
    echo ""
    echo "⚠️  IMPORTANT: Edit $INSTALL_DIR/newt.env with your Pangolin credentials!"
    echo "   1. Go to https://app.pangolin.net"
    echo "   2. Create a NEW site called 'jarvis-host'"
    echo "   3. Generate Newt credentials (NEWT_ID + NEWT_SECRET)"
    echo "   4. Paste them into $INSTALL_DIR/newt.env"
fi

# Install systemd service
cp "$SCRIPT_DIR/newt-host.service" /etc/systemd/system/newt-host.service
systemctl daemon-reload
systemctl enable newt-host

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/newt-host/newt.env — add your Pangolin NEWT_ID and NEWT_SECRET"
echo "  2. sudo systemctl start newt-host"
echo "  3. In Pangolin dashboard: add TCP resource → target 127.0.0.1:22"
echo "  4. SSH from anywhere: ssh -p <assigned-port> worker@<pangolin-server>"
echo ""
echo "This Newt runs on the HOST — independent of Kubernetes."
echo "Even if MicroK8s crashes, your SSH tunnel stays up."
