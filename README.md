# Jarvis MCP Server

An MCP (Model Context Protocol) server that runs natively on an Ubuntu server and exposes **40 tools** for an LLM to manage both the **host system** and a **MicroK8s cluster**.

```
┌──────────────────────────────────────────────────────────┐
│                    Ubuntu Server (jarvis)                 │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │           Jarvis Admin MCP Server                   │  │
│  │           (systemd service, port 8080)              │  │
│  │                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │  │
│  │  │  Cluster    │  │   System    │  │   File    │  │  │
│  │  │  Tools (19) │  │  Tools (15) │  │  Tools (4)│  │  │
│  │  │             │  │             │  │           │  │  │
│  │  │ k8s_pods    │  │ sys_info    │  │ file_read │  │  │
│  │  │ k8s_apply   │  │ sys_services│  │ file_write│  │  │
│  │  │ k8s_delete  │  │ sys_reboot  │  │ file_list │  │  │
│  │  │ k8s_scale   │  │ sys_upgrade │  │ file_find │  │  │
│  │  │ k8s_restart │  │ sys_logs    │  │           │  │  │
│  │  │ k8s_logs    │  │ ...         │  │           │  │  │
│  │  │ ...         │  │             │  │           │  │  │
│  │  └──────┬──────┘  └──────┬──────┘  └─────┬─────┘  │  │
│  │         │                │               │         │  │
│  │         ▼                ▼               ▼         │  │
│  │    ┌─────────┐    ┌──────────┐    ┌──────────┐    │  │
│  │    │ MicroK8s │    │ systemd  │    │ Filesystem│    │  │
│  │    │ kubectl  │    │ apt/snap │    │ /etc /opt │    │  │
│  │    │ (cluster)│    │ (host)   │    │ /home ... │    │  │
│  │    └─────────┘    └──────────┘    └──────────┘    │  │
│  └────────────────────────────────────────────────────┘  │
│                          ▲                               │
│                          │ SSE (127.0.0.1:8080)         │
│                     ┌────┴────┐                          │
│                     │   LLM   │  Mistral API, Claude,    │
│                     │ (remote)│  or any MCP client        │
│                     └─────────┘                          │
└──────────────────────────────────────────────────────────┘
         ▲
         │ SSH tunnel: ssh -L 8080:localhost:8080 worker@jarvis
    ┌────┴────┐
    │ Your PC  │
    └─────────┘
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

The script will:
- Create `/opt/jarvis-mcp/` and `/var/log/jarvis-mcp/`
- Install the server code and Python dependencies
- Configure systemd service and sudo permissions
- Add the user to the `microk8s` group
- Start the service

### 2. Connect from your machine

```bash
# Create an SSH tunnel
ssh -L 8080:localhost:8080 worker@192.168.1.107
```

### 3. Use with an LLM

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8080/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()

        # Let the LLM manage your cluster
        result = await session.call_tool("k8s_pods", {"all_namespaces": True})
        result = await session.call_tool("sys_info", {})
        result = await session.call_tool("k8s_restart", {
            "deployment": "jellyfin",
            "namespace": "arr"
        })
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

The `examples/agent.py` script connects Mistral's API to your MCP server in an agent loop: you type natural language, the LLM decides which tools to call, results feed back, and it repeats until done.

```
you> "Show me all pods and check system load"
  → LLM calls: k8s_pods(all_namespaces=true), sys_info()
  → Results fed back to LLM
  → LLM: "Here's the overview: 18 pods running across 5 namespaces..."
```

### Setup

```bash
# 1. Install dependencies
pip install -r examples/requirements.txt

# 2. Set your Mistral API key (get one at https://console.mistral.ai/api-keys/)
export MISTRAL_API_KEY="your-key-here"

# 3. Create SSH tunnel to the server (keep running)
./examples/tunnel.sh
# or manually: ssh -L 8080:localhost:8080 worker@192.168.1.107
```

### Usage

```bash
# Interactive chat — type natural language requests
python examples/agent.py

# Single prompt
python examples/agent.py "Restart the jellyfin deployment in the arr namespace"

# Use a specific model
python examples/agent.py --model mistral-large-latest
python examples/agent.py --model mistral-small-latest   # faster/cheaper

# Direct LAN access (if you've exposed the port)
python examples/agent.py --url http://192.168.1.107:8080/sse
```

### Example prompts

| Prompt | What the LLM will do |
|---|---|
| "Show me all pods and their status" | Calls `k8s_pods(all_namespaces=true)` |
| "Is everything healthy?" | Calls `k8s_nodes`, `k8s_pods`, `k8s_events`, `sys_info` |
| "Restart jellyfin" | Calls `k8s_restart(deployment=jellyfin, namespace=arr)` |
| "Check disk space and system load" | Calls `sys_disk`, `sys_info` |
| "Are there any system updates?" | Calls `sys_updates` |
| "Show me the last 50 log lines of the qbittorrent pod" | Calls `k8s_logs(pod=qbittorrent-xxx, namespace=arr, tail=50)` |
| "Read the microk8s config" | Calls `file_read(path=/var/snap/microk8s/current/...)` |

### Other MCP clients

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
├── requirements.txt                # Server dependencies (mcp>=1.10,<2.0)
├── .gitignore
├── server/
│   └── server.py                   # The MCP server (40 tools, ~620 lines)
├── deploy/
│   ├── deploy.sh                   # Automated deployment script
│   ├── jarvis-mcp.service          # systemd service unit
│   └── jarvis-mcp.sudoers          # sudo permissions for the MCP user
└── examples/
    ├── agent.py                    # 🤖 Mistral LLM agent (chat with your server!)
    ├── client_example.py           # Basic MCP client with demos
    ├── tunnel.sh                   # SSH tunnel helper
    └── requirements.txt            # Agent dependencies (mcp + mistralai)
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
sudo systemctl status jarvis-mcp     # Check status
sudo systemctl restart jarvis-mcp    # Restart
sudo systemctl stop jarvis-mcp       # Stop
sudo journalctl -u jarvis-mcp -f     # Follow logs
tail -f /var/log/jarvis-mcp/audit.log  # Audit trail
```

## Requirements

- Ubuntu 22.04+ (tested on 26.04)
- MicroK8s installed (`sudo snap install microk8s --classic`)
- Python 3.10+
- `python3-venv` package

## License

MIT
