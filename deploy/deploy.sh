#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/service-terminal"
LOG_DIR="/var/log/service-terminal"
SERVICE_NAME="service-terminal"
TARGET_USER="${1:-worker}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { echo -e "\033[0;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[0;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[0;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; exit 1; }

info "Running pre-flight checks..."

[ "$(id -u)" -eq 0 ] || error "This script must be run with sudo (or as root)."
command -v python3 &>/dev/null || error "python3 not found. Install it first."

if ! command -v microk8s &>/dev/null && ! [ -x /snap/bin/microk8s ]; then
    error "MicroK8s not found. Install it: sudo snap install microk8s --classic"
fi

id "$TARGET_USER" &>/dev/null || error "User '$TARGET_USER' does not exist."
ok "Pre-flight checks passed."

info "Creating directories..."
mkdir -p "$INSTALL_DIR" "$LOG_DIR"
chown -R "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR" "$LOG_DIR"
ok "Directories created."

info "Installing server code..."
cp "$SCRIPT_DIR/../server/server.py" "$INSTALL_DIR/server.py"
chown "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR/server.py"
ok "Server code installed to $INSTALL_DIR/server.py"

info "Setting up Python virtual environment..."

if ! python3 -c "import ensurepip" &>/dev/null; then
    info "Installing python3-venv..."
    apt-get update -qq
    apt-get install -y python3-venv python3-pip
fi

sudo -u "$TARGET_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$TARGET_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$SCRIPT_DIR/../requirements.txt"
ok "Dependencies installed (mcp>=1.10,<2.0)"

info "Installing systemd service..."
cp "$SCRIPT_DIR/service-terminal.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
ok "Systemd service installed."

info "Configuring sudo permissions..."
cp "$SCRIPT_DIR/service-terminal.sudoers" "/etc/sudoers.d/${SERVICE_NAME}"
chmod 440 "/etc/sudoers.d/${SERVICE_NAME}"
visudo -c -f "/etc/sudoers.d/${SERVICE_NAME}" || error "Sudoers file has syntax errors!"
ok "Sudo permissions configured."

info "Adding $TARGET_USER to microk8s group..."
usermod -a -G microk8s "$TARGET_USER"
ok "User added to microk8s group (re-login required for group to take effect)."

info "Starting ${SERVICE_NAME} service..."
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 3

info "Verifying installation..."

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "MCP server is running."
else
    error "MCP server failed to start. Check: sudo journalctl -u ${SERVICE_NAME} -n 30"
fi

MCP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/sse --max-time 5 || echo "000")
if [ "$MCP_CODE" = "200" ]; then
    ok "MCP SSE endpoint: http://127.0.0.1:8080/sse (HTTP $MCP_CODE)"
else
    warn "MCP SSE endpoint returned HTTP $MCP_CODE — may still be starting."
fi

echo ""
echo "======================================================================"
echo "  Service Terminal MCP Server — Installation Complete"
echo "======================================================================"
echo ""
echo "  MCP Server:"
echo "    Service:     $SERVICE_NAME (enabled, running)"
echo "    SSE:         http://127.0.0.1:8080/sse (localhost only)"
echo "    Audit log:   $LOG_DIR/audit.log"
echo "    Server log:  $LOG_DIR/server.log"
echo ""
echo "  Authentication:"
echo "    Set SERVICE_TERMINAL_TOKEN environment variable for Bearer token auth"
echo "    Edit systemd service: sudo systemctl edit $SERVICE_NAME"
echo "    Add: Environment=\"SERVICE_TERMINAL_TOKEN=your-secure-token\""
echo "    Then: sudo systemctl daemon-reload && sudo systemctl restart $SERVICE_NAME"
echo ""
echo "  Service management:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "    sudo journalctl -u $SERVICE_NAME -f"
echo "    tail -f $LOG_DIR/audit.log"
echo ""
echo "======================================================================"
