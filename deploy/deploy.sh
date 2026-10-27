#!/usr/bin/env bash
# =============================================================================
# Jarvis MCP Server — Deployment Script
# =============================================================================
# Run this on the target Ubuntu server (with MicroK8s installed) as a user
# with sudo access. It sets up everything needed to run the MCP server.
#
# Usage:
#   sudo bash deploy.sh [--user worker]
#
# Requirements:
#   - Ubuntu 22.04+ (tested on 26.04)
#   - MicroK8s installed and running (snap install microk8s --classic)
#   - Python 3.10+
#   - sudo access
# =============================================================================

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────
INSTALL_DIR="/opt/jarvis-mcp"
LOG_DIR="/var/log/jarvis-mcp"
SERVICE_NAME="jarvis-mcp"
TARGET_USER="${1:-worker}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Helpers ────────────────────────────────────────────────────────────────
info()  { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[0;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

# ── Pre-flight checks ──────────────────────────────────────────────────────
info "Running pre-flight checks..."

[ "$(id -u)" -eq 0 ] || error "This script must be run with sudo (or as root)."

command -v python3 &>/dev/null || error "python3 not found. Install it first."

if ! command -v microk8s &>/dev/null && ! [ -x /snap/bin/microk8s ]; then
    error "MicroK8s not found. Install it: sudo snap install microk8s --classic"
fi

id "$TARGET_USER" &>/dev/null || error "User '$TARGET_USER' does not exist."

ok "Pre-flight checks passed."

# ── Step 1: Create directories ─────────────────────────────────────────────
info "Creating directories..."
mkdir -p "$INSTALL_DIR" "$LOG_DIR"
chown -R "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR" "$LOG_DIR"
ok "Directories created."

# ── Step 2: Install server code ────────────────────────────────────────────
info "Installing server code..."
cp "$SCRIPT_DIR/../server/server.py" "$INSTALL_DIR/server.py"
chown "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR/server.py"
ok "Server code installed to $INSTALL_DIR/server.py"

# ── Step 3: Create Python venv and install dependencies ─────────────────────
info "Setting up Python virtual environment..."

# Ensure python3-venv is available
if ! python3 -c "import ensurepip" &>/dev/null; then
    info "Installing python3-venv..."
    apt-get update -qq
    apt-get install -y python3-venv python3-pip
fi

sudo -u "$TARGET_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$TARGET_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$SCRIPT_DIR/../requirements.txt"
ok "Dependencies installed (mcp>=1.10,<2.0)"

# ── Step 4: Install systemd service ────────────────────────────────────────
info "Installing systemd service..."
cp "$SCRIPT_DIR/jarvis-mcp.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
ok "Systemd service installed."

# ── Step 5: Configure sudoers ──────────────────────────────────────────────
info "Configuring sudo permissions..."
cp "$SCRIPT_DIR/jarvis-mcp.sudoers" "/etc/sudoers.d/${SERVICE_NAME}"
chmod 440 "/etc/sudoers.d/${SERVICE_NAME}"
# Validate sudoers syntax
visudo -c -f "/etc/sudoers.d/${SERVICE_NAME}" || error "Sudoers file has syntax errors!"
ok "Sudo permissions configured."

# ── Step 6: Add user to microk8s group ─────────────────────────────────────
info "Adding $TARGET_USER to microk8s group..."
usermod -a -G microk8s "$TARGET_USER"
ok "User added to microk8s group (re-login required for group to take effect)."

# ── Step 7: Enable and start the service ───────────────────────────────────
info "Starting ${SERVICE_NAME} service..."
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 3

# ── Step 8: Verify ─────────────────────────────────────────────────────────
info "Verifying installation..."

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running."
else
    error "Service failed to start. Check logs: sudo journalctl -u ${SERVICE_NAME} -n 30"
fi

HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/sse --max-time 5 || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    ok "SSE endpoint responding on http://127.0.0.1:8080/sse (HTTP $HTTP_CODE)"
else
    warn "SSE endpoint returned HTTP $HTTP_CODE — server may still be starting up."
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "======================================================================"
echo "  Jarvis MCP Server — Installation Complete"
echo "======================================================================"
echo ""
echo "  Server code:   $INSTALL_DIR/server.py"
echo "  Service:       $SERVICE_NAME (enabled, running)"
echo "  SSE endpoint:  http://127.0.0.1:8080/sse"
echo "  Audit log:     $LOG_DIR/audit.log"
echo "  Server log:    $LOG_DIR/server.log"
echo ""
echo "  To connect from your machine, create an SSH tunnel:"
echo "    ssh -L 8080:localhost:8080 ${TARGET_USER}@<server-ip>"
echo ""
echo "  Then point your MCP client at:"
echo "    http://localhost:8080/sse"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status $SERVICE_NAME     # check status"
echo "    sudo systemctl restart $SERVICE_NAME    # restart"
echo "    sudo journalctl -u $SERVICE_NAME -f     # follow logs"
echo "    tail -f $LOG_DIR/audit.log              # audit trail"
echo ""
echo "======================================================================"
