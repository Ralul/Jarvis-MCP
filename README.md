# Jarvis MCP Server

An MCP (Model Context Protocol) server that runs natively on an Ubuntu server and exposes **40 tools** for an LLM to manage both the **host system** and a **MicroK8s cluster**.

Remote access is handled by **Pangolin** (host-level Newt client) — no SSH tunnel needed, and access survives Kubernetes outages.

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Ubuntu Server (jarvis)                           │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  MCP Server — systemd service                                 │    │
│  │  127.0.0.1:8080 (SSE transport)                               │    │
│  │                                                               │    │
│  │  40 tools:                                                    │    │
│  │  • Cluster (19): kubectl, pods, deployments, apply, scale...  │    │
│  │  • System (15):  systemd, apt, snap, disk, network, reboot... │    │
│  │  • Files (4):    read, write, list, find                      │    │
│  │  • Meta (2):     audit_log, server_info                       │    │
│  └──────────────────────────┬───────────────────────────────────┘    │
│                             │                                        │
│  ┌──────────────────────────▼───────────────────────────────────┐    │
│  │  Newt (Pangolin host client) — systemd service                │    │
│  │  Runs on host OS, independent of Kubernetes                   │    │
│  │                                                               │    │
│  │  Proxies:                                                     │    │
│  │  • https://mcp.yourdomain.com  → 127.0.0.1:8080 (MCP/SSE)     │    │
│  │  • tcp://pangolin:21022       → 127.0.0.1:22    (SSH)         │    │
│  └──────────────────────────┬───────────────────────────────────┘    │
│                             │                                        │
│                    ┌────────┴────────┐                               │
│                    │  Pangolin Cloud  │                               │
│                    │  app.pangolin.net│                               │
│                    └────────┬────────┘                               │
│                             │                                        │
│  ┌──────────────────────────▼───────────────────────────────────┐    │
│  │  Your machine / LLM client                                    │    │
│  │                                                               │    │
│  │  MCP client → https://mcp.yourdomain.com/sse                  │    │
│  │  SSH        → ssh -p 21022 worker@pangolin-server             │    │
│  │  LLM agent  → connects to MCP via domain, no tunnel needed    │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Kubernetes cluster (separate — can crash without affecting access)  │
│  • MicroK8s (arr stack, portainer, traefik, etc.)                   │
│  • Newt pods in k8s (for arr services via Pangolin)                  │
└──────────────────────────────────────────────────────────────────────┘
```

## Features

- **40 tools** across 4 categories: Cluster (19), System (15), Files (4), Meta (2)
- **Safety guardrails**: destructive operations require `confirm=true`
- **Dry-run by default** for `k8s_apply`
- **Full audit trail**: every tool call logged
- **Path restrictions**: file tools limited to safe directories
- **Remote access via Pangolin**: MCP server accessible via HTTPS domain, SSH via TCP tunnel — both independent of Kubernetes

## Quick Start

### 1. Deploy the MCP server

```bash
git clone <repo-url> && cd jarvis-mcp
sudo bash deploy/deploy.sh
```

This installs:
- MCP server at `/opt/jarvis-mcp/server.py`
- Python venv with `mcp>=1.10,<2.0`
- systemd service `jarvis-mcp` (enabled, auto-starts on boot)
- Sudo permissions for safe commands
- Audit logging to `/var/log/jarvis-mcp/audit.log`

### 2. Set up host-level Newt (Pangolin client)

```bash
sudo bash deploy/setup-newt-host.sh
```

This installs:
- Newt binary at `/opt/newt-host/newt`
- systemd service `newt-host` (enabled, auto-starts on boot)
- Env file template at `/opt/newt-host/newt.env`

### 3. Configure Pangolin

**a) Create a new site in Pangolin** at https://app.pangolin.net:
- Name: `jarvis-host`
- Generate Newt credentials (NEWT_ID + NEWT_SECRET)

**b) Fill in credentials on the server:**
```bash
sudo nano /opt/newt-host/newt.env
# Set NEWT_ID and NEWT_SECRET from Pangolin
sudo systemctl start newt-host
```

**c) Add resources in Pangolin dashboard (jarvis-host site):**

| Type | Name | Domain / Port | Target |
|---|---|---|---|
| HTTP | `jarvis-mcp` | `mcp.yourdomain.com` | `127.0.0.1:8080` |
| TCP | `jarvis-ssh` | (auto-assigned port) | `127.0.0.1:22` |

### 4. Connect

**MCP server via domain:**
```
https://mcp.yourdomain.com/sse
```
Any MCP-compatible client or LLM agent can connect here.

**SSH via Pangolin:**
```bash
ssh -p <assigned-port> worker@<pangolin-server>
```

**LLM agent example:**
```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("https://mcp.yourdomain.com/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("k8s_pods", {"all_namespaces": True})
        result = await session.call_tool("sys_info", {})
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

## Project Structure

```
jarvis-mcp/
├── README.md                       # This file
├── requirements.txt                # mcp>=1.10,<2.0
├── .gitignore
├── server/
│   └── server.py                   # MCP server (40 tools, ~620 lines)
└── deploy/
    ├── deploy.sh                   # MCP server deployment
    ├── setup-newt-host.sh          # Host-level Newt (Pangolin) setup
    ├── jarvis-mcp.service          # MCP server systemd unit
    ├── jarvis-mcp.sudoers          # Sudo permissions
    ├── newt-host.service           # Host Newt systemd unit
    └── newt-host.env.example       # Newt credentials template
```

## Security Model

| Layer | Protection |
|---|---|
| **Network** | MCP server binds to `127.0.0.1:8080` — not directly exposed |
| **Remote access** | Via Pangolin (HTTPS domain with TLS, or TCP tunnel) |
| **Host independence** | Newt runs on host OS — survives Kubernetes outages |
| **Confirmation** | Destructive ops require `confirm=true` |
| **Dry-run** | `k8s_apply` defaults to `--dry-run=server` |
| **Path restrictions** | File tools limited to `/etc`, `/opt`, `/home`, `/root`, `/var/snap/microk8s`, `/var/lib`, `/tmp`, `/srv` |
| **OS permissions** | Server runs as `worker` user — can't read root-only files |
| **Audit trail** | Every tool call logged to `/var/log/jarvis-mcp/audit.log` |
| **Sudo allowlist** | Only specific commands allowed passwordless |

## Service Management

```bash
# MCP Server
sudo systemctl status jarvis-mcp
sudo systemctl restart jarvis-mcp
sudo journalctl -u jarvis-mcp -f
tail -f /var/log/jarvis-mcp/audit.log

# Host Newt (Pangolin client)
sudo systemctl status newt-host
sudo systemctl restart newt-host
tail -f /var/log/newt-host.log
```

## Requirements

- Ubuntu 22.04+ (tested on 26.04)
- MicroK8s installed (`sudo snap install microk8s --classic`)
- Python 3.10+ with `python3-venv`
- Pangolin account (https://app.pangolin.net) for remote access

## License

MIT
