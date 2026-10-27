# Jarvis MCP Server

An MCP (Model Context Protocol) server that runs natively on an Ubuntu server and exposes **40 tools** for an LLM to manage both the **host system** and a **MicroK8s cluster**.

Two services run on the server — **no SSH tunnel needed**:

```
┌──────────────────────────────────────────────────────────────────┐
│                    Ubuntu Server (jarvis)                         │
│                                                                  │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐  │
│  │  MCP Server (:8080)      │    │  Agent Service (:8081)       │  │
│  │  127.0.0.1 only          │◄───│  0.0.0.0 (LAN accessible)    │  │
│  │                          │    │                             │  │
│  │  40 tools:               │    │  - Web chat UI              │  │
│  │  • Cluster (kubectl)     │    │  - REST API (/chat)         │  │
│  │  • System (systemd, apt) │    │  - Mistral LLM agent loop   │  │
│  │  • Files (read/write)    │    │  - Conversation history     │  │
│  │  • Audit logging         │    │  - Auto-starts on boot      │  │
│  └─────────────────────────┘    └────────────┬────────────────┘  │
│                                              │                   │
│                                         ┌────┴────┐              │
│                                         │  Mistral │              │
│                                         │   API    │              │
│                                         │ (cloud)  │              │
│                                         └────┬────┘              │
│                                              │                   │
│  ┌───────────────────────────────────────────┘                   │
│  │  Your browser: http://192.168.1.107:8081/                     │
│  │  curl: curl -X POST http://192.168.1.107:8081/chat \          │
│  │        -H 'Content-Type: application/json' \                  │
│  │        -d '{"message": "Show all pods"}'                      │
│  └──────────────────────────────────────────────────────────────┘
│                                                                  │
│  Both services: systemd, enabled, auto-restart on failure        │
└──────────────────────────────────────────────────────────────────┘
```

## Features

- **40 tools** across 4 categories: Cluster (19), System (15), Files (4), Meta (2)
- **Safety guardrails**: destructive operations require `confirm=true`
- **Dry-run by default** for `k8s_apply`
- **Full audit trail**: every tool call logged with timestamp, args, and result
- **Path restrictions**: file tools limited to safe directories
- **Localhost-only**: binds to `127.0.0.1`, use SSH tunnel for remote access
- **systemd service**: auto-starts on boot, auto-restarts on failure

## Quick Start

### 1. Deploy to your server

```bash
# Clone this repo on the server (or copy the files)
git clone <repo-url> && cd jarvis-mcp

# Run the deployment script (requires sudo)
sudo bash deploy/deploy.sh
```

The script installs **both services**:
- **MCP Server** on `127.0.0.1:8080` — the tool server (localhost only, secure)
- **Agent Service** on `0.0.0.0:8081` — the AI chat (LAN accessible, no tunnel needed)

### 2. Set your Mistral API key

```bash
sudo nano /opt/jarvis-mcp/agent.env
# Set: MISTRAL_API_KEY=your-key-here
sudo systemctl restart jarvis-agent
```

### 3. Open the chat UI in your browser

```
http://192.168.1.107:8081/
```

No SSH tunnel needed. Type natural language and the AI agent manages your server.

### 4. Or use the REST API

```bash
curl -X POST http://192.168.1.107:8081/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show me all pods and check system load"}'
```

### 5. Or connect any MCP client (with SSH tunnel)

```bash
ssh -L 8080:localhost:8080 worker@192.168.1.107
# Then point your MCP client at: http://localhost:8080/sse
```

## All Tools

### Cluster Tools (19)

| Tool | Description | Dangerous? |
|---|---|---|
| `k8s_pods` | List pods (optionally all namespaces) | No |
| `k8s_deployments` | List deployments | No |
| `k8s_services` | List services | No |
| `k8s_describe` | Describe any resource | No |
| `k8s_logs` | Get pod logs | No |
| `k8s_events` | Get cluster events | No |
| `k8s_nodes` | Show node info | No |
| `k8s_apply` | Apply YAML manifest (dry-run by default) | Dry-run safe |
| `k8s_delete` | Delete a resource | **Yes** (confirm=true) |
| `k8s_scale` | Scale a deployment | No |
| `k8s_restart` | Rolling restart a deployment | No |
| `k8s_rollout_status` | Check rollout status | No |
| `k8s_get_yaml` | Get resource YAML | No |
| `k8s_namespaces` | List namespaces | No |
| `k8s_resource_usage` | Pod resource usage (needs metrics-server) | No |
| `k8s_exec` | Execute command in a pod | No |
| `k8s_microk8s_status` | MicroK8s status and addons | No |
| `k8s_enable_addon` | Enable a MicroK8s addon | No |
| `k8s_disable_addon` | Disable a MicroK8s addon | **Yes** (confirm=true) |

### System Tools (15)

| Tool | Description | Dangerous? |
|---|---|---|
| `sys_info` | OS, CPU, memory, disk, uptime overview | No |
| `sys_services` | List systemd services (running/failed/all) | No |
| `sys_service_control` | Start/stop/restart/reload/enable/disable | stop/disable: **Yes** |
| `sys_service_status` | Get service status | No |
| `sys_logs` | journalctl logs (filter by service/priority) | No |
| `sys_updates` | Check for apt + snap updates | No |
| `sys_upgrade` | Upgrade all packages | **Yes** (confirm=true) |
| `sys_processes` | Top processes by CPU or memory | No |
| `sys_network` | Network interfaces and listening ports | No |
| `sys_disk` | Disk usage and mount points | No |
| `sys_reboot` | Reboot the server | **Yes** (confirm=true) |
| `sys_shutdown` | Shut down the server | **Yes** (confirm=true) |
| `sys_snap_list` | List snap packages | No |
| `sys_apt_install` | Install a package | **Yes** (confirm=true) |
| `sys_apt_remove` | Remove a package | **Yes** (confirm=true) |

### File Tools (4)

| Tool | Description | Dangerous? |
|---|---|---|
| `file_read` | Read a file (restricted paths) | No |
| `file_write` | Write to a file (restricted paths) | **Yes** (confirm=true) |
| `file_list` | List directory contents | No |
| `file_find` | Find files by pattern | No |

### Meta Tools (2)

| Tool | Description |
|---|---|
| `audit_log` | Show recent audit log entries |
| `server_info` | Show server info and tool list |

## Connecting an LLM (Mistral)

### Option A: Agent Service on the server (no SSH tunnel — recommended)

The `server/agent_service.py` runs **on the server itself** as a systemd service. It connects to the MCP server on `localhost` directly and exposes a web chat UI on the LAN.

```
Browser ──► http://192.168.1.107:8081/ ──► Agent Service ──► MCP Server (localhost:8080)
                                                    └──► Mistral API (cloud)
```

**Setup:**

```bash
# 1. Set your Mistral API key
sudo nano /opt/jarvis-mcp/agent.env
# Set: MISTRAL_API_KEY=your-key-here
sudo systemctl restart jarvis-agent

# 2. Open in your browser
http://192.168.1.107:8081/
```

**REST API:**

```bash
# Send a message
curl -X POST http://192.168.1.107:8081/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Show me all pods and check system load"}'

# Response:
# {"response": "Here's the overview...", "session_id": "...", "tool_calls": ["k8s_pods", "sys_info"]}

# Health check
curl http://192.168.1.107:8081/health

# List tools
curl http://192.168.1.107:8081/tools

# Reset a conversation
curl -X POST "http://192.168.1.107:8081/reset?session_id=xxx"
```

**Features:**
- Web chat UI (dark theme, markdown rendering, tool call badges)
- Conversation history (per session, stored in memory)
- Persistent MCP connection (established on startup)
- Optional API key auth (set `AGENT_API_KEY` in `agent.env`)
- Auto-starts on boot, auto-restarts on failure

### Option B: Agent script on your machine (needs SSH tunnel)

The `examples/agent.py` script connects Mistral's API to your MCP server from your local machine:

```bash
# 1. Install dependencies
pip install -r examples/requirements.txt

# 2. Set your Mistral API key
export MISTRAL_API_KEY="your-key-here"

# 3. Create SSH tunnel (keep running)
./examples/tunnel.sh

# 4. Start chatting
python examples/agent.py
```

**Example prompts:**

| Prompt | What the LLM will do |
|---|---|
| "Show me all pods and their status" | Calls `k8s_pods(all_namespaces=true)` |
| "Is everything healthy?" | Calls `k8s_nodes`, `k8s_pods`, `k8s_events`, `sys_info` |
| "Restart jellyfin" | Calls `k8s_restart(deployment=jellyfin, namespace=arr)` |
| "Check disk space and system load" | Calls `sys_disk`, `sys_info` |
| "Are there any system updates?" | Calls `sys_updates` |
| "Show me the last 50 log lines of qbittorrent" | Calls `k8s_logs(pod=qbittorrent-xxx, namespace=arr, tail=50)` |

### Option C: Other MCP clients (needs SSH tunnel)

Any MCP-compatible client can connect to `http://localhost:8080/sse` (after SSH tunnel):

- **Claude Desktop** — add to `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "jarvis": {
        "url": "http://localhost:8080/sse"
      }
    }
  }
  ```
- **Cursor IDE** — Settings → MCP → add SSE server URL
- **Continue.dev** — `.continue/config.json` MCP servers section
- **Custom apps** — use the `mcp` Python SDK (see `examples/client_example.py`)

## Project Structure

```
jarvis-mcp/
├── README.md                       # This file
├── requirements.txt                # Server + agent dependencies
├── .gitignore
├── server/
│   ├── server.py                   # MCP server (40 tools, ~620 lines)
│   └── agent_service.py            # AI agent web service (FastAPI, chat UI)
├── deploy/
│   ├── deploy.sh                   # Automated deployment (both services)
│   ├── jarvis-mcp.service          # MCP server systemd unit
│   ├── jarvis-agent.service        # Agent service systemd unit
│   └── jarvis-mcp.sudoers          # sudo permissions for the MCP user
└── examples/
    ├── agent.py                    # CLI agent (Mistral + MCP, needs SSH tunnel)
    ├── client_example.py           # Basic MCP client with demos
    ├── tunnel.sh                   # SSH tunnel helper
    └── requirements.txt            # CLI agent dependencies
```

## Security Model

| Layer | Protection |
|---|---|
| **Network** | Binds to `127.0.0.1:8080` only — no direct LAN exposure |
| **Access** | SSH tunnel required for remote access |
| **Confirmation** | Destructive ops require `confirm=true` parameter |
| **Dry-run** | `k8s_apply` defaults to `--dry-run=server` |
| **Path restrictions** | File tools limited to `/etc`, `/opt`, `/home`, `/root`, `/var/snap/microk8s`, `/var/lib`, `/tmp`, `/srv` |
| **OS permissions** | Server runs as `worker` user — can't read root-only files |
| **Audit trail** | Every tool call logged to `/var/log/jarvis-mcp/audit.log` |
| **Sudo allowlist** | Only specific commands allowed passwordless via sudoers |

## Service Management

```bash
# Both services
sudo systemctl status jarvis-mcp jarvis-agent
sudo systemctl restart jarvis-mcp jarvis-agent

# MCP Server (port 8080, localhost only)
sudo systemctl status jarvis-mcp
sudo journalctl -u jarvis-mcp -f

# Agent Service (port 8081, LAN accessible)
sudo systemctl status jarvis-agent
sudo journalctl -u jarvis-agent -f

# Logs
tail -f /var/log/jarvis-mcp/server.log    # MCP server
tail -f /var/log/jarvis-mcp/agent.log     # Agent service
tail -f /var/log/jarvis-mcp/audit.log     # Audit trail (every tool call)

# Agent configuration
sudo nano /opt/jarvis-mcp/agent.env       # Edit API key, model, etc.
sudo systemctl restart jarvis-agent       # Apply changes

## Requirements

- Ubuntu 22.04+ (tested on 26.04)
- MicroK8s installed (`sudo snap install microk8s --classic`)
- Python 3.10+
- `python3-venv` package

## License

MIT
