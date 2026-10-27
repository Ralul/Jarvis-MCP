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

# ── Step 7: Enable and start the MCP server ────────────────────────────────
info "Starting ${SERVICE_NAME} service..."
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
sleep 3

# ── Step 8: Install Agent Service (AI Chat — no SSH tunnel needed) ──────────
info "Installing Agent Service..."
AGENT_SERVICE="jarvis-agent"

# Copy agent service code
cp "$SCRIPT_DIR/../server/agent_service.py" "$INSTALL_DIR/agent_service.py"
chown "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR/agent_service.py"

# Install additional Python dependencies for the agent (FastAPI, uvicorn, mistralai)
sudo -u "$TARGET_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet fastapi uvicorn mistralai

# Install agent systemd service
cp "$SCRIPT_DIR/jarvis-agent.service" "/etc/systemd/system/${AGENT_SERVICE}.service"

# Create env file template for the agent (user fills in MISTRAL_API_KEY)
if [ ! -f "$INSTALL_DIR/agent.env" ]; then
    cat > "$INSTALL_DIR/agent.env" << 'ENVEOF'
# Jarvis Agent Configuration
# Get your API key at: https://console.mistral.ai/api-keys/
MISTRAL_API_KEY=your-mistral-api-key-here
AGENT_MODEL=mistral-large-latest
# AGENT_API_KEY=optional-bearer-token-for-chat-api
# MCP_URL=http://127.0.0.1:8080/sse
# AGENT_PORT=8081
ENVEOF
    chown "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR/agent.env"
    chmod 600 "$INSTALL_DIR/agent.env"
    warn "Created $INSTALL_DIR/agent.env — edit it to set your MISTRAL_API_KEY!"
fi

systemctl daemon-reload
systemctl enable "$AGENT_SERVICE"
systemctl restart "$AGENT_SERVICE"
sleep 3

# ── Step 9: Verify everything ──────────────────────────────────────────────
info "Verifying installation..."

# Check MCP server
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

# Check Agent service
if systemctl is-active --quiet "$AGENT_SERVICE"; then
    ok "Agent service is running."
else
    warn "Agent service failed to start (likely missing MISTRAL_API_KEY). Check: sudo journalctl -u ${AGENT_SERVICE} -n 30"
fi

AGENT_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/health --max-time 5 || echo "000")
if [ "$AGENT_CODE" = "200" ]; then
    ok "Agent health endpoint: http://0.0.0.0:8081/health (HTTP $AGENT_CODE)"
else
    warn "Agent health endpoint returned HTTP $AGENT_CODE."
fi

# ── Done ───────────────────────────────────────────────────────────────────
SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "======================================================================"
echo "  Jarvis MCP Server + Agent — Installation Complete"
echo "======================================================================"
echo ""
echo "  MCP Server:"
echo "    Service:     $SERVICE_NAME (enabled, running)"
echo "    SSE:         http://127.0.0.1:8080/sse (localhost only)"
echo ""
echo "  AI Agent (no SSH tunnel needed!):"
echo "    Service:     $AGENT_SERVICE (enabled, running)"
echo "    Web UI:      http://${SERVER_IP}:8081/"
echo "    Chat API:    http://${SERVER_IP}:8081/chat"
echo "    Health:      http://${SERVER_IP}:8081/health"
echo ""
echo "  ⚠️  IMPORTANT: Set your Mistral API key:"
echo "    sudo nano $INSTALL_DIR/agent.env"
echo "    → Set MISTRAL_API_KEY=your-key-here"
echo "    → sudo systemctl restart $AGENT_SERVICE"
echo ""
echo "  Then open in your browser:"
echo "    http://${SERVER_IP}:8081/"
echo ""
echo "  Logs:"
echo "    MCP:    $LOG_DIR/server.log"
echo "    Agent:  $LOG_DIR/agent.log"
echo "    Audit:  $LOG_DIR/audit.log"
echo ""
echo "  Service management:"
echo "    sudo systemctl status $SERVICE_NAME $AGENT_SERVICE"
echo "    sudo systemctl restart $SERVICE_NAME $AGENT_SERVICE"
echo ""
echo "======================================================================"
