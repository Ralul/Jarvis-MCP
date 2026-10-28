#!/usr/bin/env python3

import os
import subprocess
import logging
import datetime
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

AUDIT_LOG_DIR = "/var/log/service-terminal"
AUDIT_LOG = os.path.join(AUDIT_LOG_DIR, "audit.log")
SERVER_LOG = os.path.join(AUDIT_LOG_DIR, "server.log")
KUBECTL = "/snap/bin/microk8s.kubectl"
MICROK8S = "/snap/bin/microk8s"
HOST = "127.0.0.1"
PORT = 8080

BEARER_TOKEN = os.environ.get("SERVICE_TERMINAL_TOKEN", "")

SAFE_FILE_PREFIXES = [
    "/etc/",
    "/opt/",
    "/home/",
    "/root/",
    "/var/snap/microk8s/",
    "/var/lib/",
    "/tmp/",
    "/srv/",
]

os.makedirs(AUDIT_LOG_DIR, exist_ok=True)
_handlers = [logging.StreamHandler()]
try:
    _handlers.insert(0, logging.FileHandler(SERVER_LOG))
except PermissionError:
    pass
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger("service-terminal")


def audit(tool: str, args: str, result: str, status: str = "ok") -> None:
    ts = datetime.datetime.now().isoformat()
    entry = f"{ts} | {tool} | {args} | {status} | {result[:500]}"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(entry + "\n")
    except PermissionError:
        try:
            with open(os.path.expanduser("~/service-terminal-audit.log"), "a") as f:
                f.write(entry + "\n")
        except Exception:
            pass
    except Exception:
        pass
    logger.info("AUDIT [%s] %s: %s", status, tool, args[:200])


def validate_token(request):
    if not BEARER_TOKEN:
        return True
    auth_header = request.headers.get("Authorization", "")
    expected_header = f"Bearer {BEARER_TOKEN}"
    return auth_header == expected_header


def run(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        out = r.stdout.strip()
        if r.stderr.strip():
            out += "\n[stderr] " + r.stderr.strip()
        return out if out else "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    except Exception as e:
        return f"ERROR: {e}"


def require_confirm(confirm: bool, action: str) -> Optional[str]:
    if not confirm:
        return (
            f"DANGER: This action ({action}) is destructive.\n"
            f"Set confirm=true to proceed."
        )
    return None


def check_safe_path(path: str) -> bool:
    abs_path = os.path.abspath(path)
    return any(abs_path == p.rstrip("/") or abs_path.startswith(p) for p in SAFE_FILE_PREFIXES)


class AuthenticatedFastMCP(FastMCP):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
    async def handle_request(self, request, context):
        if not validate_token(request):
            return {"error": "Unauthorized - Invalid or missing Bearer token"}
        return await super().handle_request(request, context)


mcp = AuthenticatedFastMCP(
    "service-terminal",
    host=HOST,
    port=PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*"],
        allowed_origins=["*"],
    ),
)


@mcp.tool()
def k8s_pods(namespace: str = "", all_namespaces: bool = False) -> str:
    """List pods. Set all_namespaces=true to see every pod in the cluster."""
    ns = "--all-namespaces" if all_namespaces else (f"-n {namespace}" if namespace else "")
    result = run(f"{KUBECTL} get pods {ns} -o wide")
    audit("k8s_pods", f"ns={namespace or 'default'} all={all_namespaces}", result)
    return result


@mcp.tool()
def k8s_deployments(namespace: str = "", all_namespaces: bool = False) -> str:
    """List all deployments."""
    ns = "--all-namespaces" if all_namespaces else (f"-n {namespace}" if namespace else "")
    result = run(f"{KUBECTL} get deployments {ns}")
    audit("k8s_deployments", f"ns={namespace or 'default'} all={all_namespaces}", result)
    return result


@mcp.tool()
def k8s_services(namespace: str = "", all_namespaces: bool = False) -> str:
    """List all services."""
    ns = "--all-namespaces" if all_namespaces else (f"-n {namespace}" if namespace else "")
    result = run(f"{KUBECTL} get svc {ns} -o wide")
    audit("k8s_services", f"ns={namespace or 'default'} all={all_namespaces}", result)
    return result


@mcp.tool()
def k8s_describe(resource_type: str, name: str, namespace: str = "") -> str:
    """Describe a Kubernetes resource. E.g. resource_type=pod, name=jellyfin-xxx, namespace=arr"""
    ns = f"-n {namespace}" if namespace else ""
    result = run(f"{KUBECTL} describe {resource_type} {name} {ns}")
    audit("k8s_describe", f"{resource_type}/{name} ns={namespace or 'default'}", result)
    return result


@mcp.tool()
def k8s_logs(
    pod: str, namespace: str = "default", tail: int = 50, container: str = ""
) -> str:
    """Get logs from a pod. tail controls how many lines (default 50)."""
    c = f"-c {container}" if container else ""
    result = run(
        f"{KUBECTL} logs -n {namespace} {pod} --tail={tail} {c} 2>&1"
    )
    audit("k8s_logs", f"pod={pod} ns={namespace} tail={tail}", result)
    return result


@mcp.tool()
def k8s_events(namespace: str = "", all_namespaces: bool = True, tail: int = 30) -> str:
    """Get recent cluster events sorted by timestamp."""
    ns = "--all-namespaces" if all_namespaces else (f"-n {namespace}" if namespace else "")
    result = run(
        f"{KUBECTL} get events {ns} --sort-by='.lastTimestamp' 2>&1 | tail -{tail}"
    )
    audit("k8s_events", f"ns={namespace or 'all'} tail={tail}", result)
    return result


@mcp.tool()
def k8s_nodes() -> str:
    """Show cluster nodes with status and resource capacity."""
    result = run(f"{KUBECTL} get nodes -o wide")
    audit("k8s_nodes", "", result)
    return result


@mcp.tool()
def k8s_apply(manifest: str, dry_run: bool = True) -> str:
    """Apply a Kubernetes YAML manifest. Defaults to dry-run; set dry_run=false to actually apply."""
    import tempfile

    dr = "--dry-run=server" if dry_run else ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(manifest)
        path = f.name
    try:
        result = run(f"{KUBECTL} apply -f {path} {dr} 2>&1")
    finally:
        os.unlink(path)
    audit("k8s_apply", f"dry_run={dry_run} manifest_len={len(manifest)}", result)
    return result


@mcp.tool()
def k8s_delete(
    resource_type: str, name: str, namespace: str = "", confirm: bool = False
) -> str:
    """Delete a Kubernetes resource. REQUIRES confirm=true."""
    err = require_confirm(confirm, f"delete {resource_type}/{name}")
    if err:
        audit("k8s_delete", f"{resource_type}/{name} ns={namespace}", err, "blocked")
        return err
    ns = f"-n {namespace}" if namespace else ""
    result = run(f"{KUBECTL} delete {resource_type} {name} {ns} 2>&1")
    audit("k8s_delete", f"{resource_type}/{name} ns={namespace}", result)
    return result


@mcp.tool()
def k8s_scale(deployment: str, replicas: int, namespace: str = "default") -> str:
    """Scale a deployment to a number of replicas."""
    result = run(
        f"{KUBECTL} scale deployment {deployment} --replicas={replicas} -n {namespace} 2>&1"
    )
    audit("k8s_scale", f"{deployment} -> {replicas} ns={namespace}", result)
    return result


@mcp.tool()
def k8s_restart(deployment: str, namespace: str = "default") -> str:
    """Restart a deployment (rolling restart)."""
    result = run(
        f"{KUBECTL} rollout restart deployment {deployment} -n {namespace} 2>&1"
    )
    audit("k8s_restart", f"{deployment} ns={namespace}", result)
    return result


@mcp.tool()
def k8s_rollout_status(deployment: str, namespace: str = "default") -> str:
    """Check the rollout status of a deployment."""
    result = run(
        f"{KUBECTL} rollout status deployment {deployment} -n {namespace} 2>&1"
    )
    audit("k8s_rollout_status", f"{deployment} ns={namespace}", result)
    return result


@mcp.tool()
def k8s_get_yaml(resource_type: str, name: str, namespace: str = "") -> str:
    """Get the full YAML definition of a resource."""
    ns = f"-n {namespace}" if namespace else ""
    result = run(f"{KUBECTL} get {resource_type} {name} {ns} -o yaml 2>&1")
    audit("k8s_get_yaml", f"{resource_type}/{name} ns={namespace or 'default'}", result)
    return result


@mcp.tool()
def k8s_namespaces() -> str:
    """List all namespaces."""
    result = run(f"{KUBECTL} get namespaces")
    audit("k8s_namespaces", "", result)
    return result


@mcp.tool()
def k8s_resource_usage() -> str:
    """Show pod resource usage (requires metrics-server addon)."""
    result = run(f"{KUBECTL} top pods --all-namespaces 2>&1")
    audit("k8s_resource_usage", "", result)
    return result


@mcp.tool()
def k8s_exec(
    pod: str, command: str, namespace: str = "default", container: str = ""
) -> str:
    """Execute a command inside a pod container."""
    c = f"-c {container}" if container else ""
    result = run(
        f"{KUBECTL} exec -n {namespace} {pod} {c} -- {command} 2>&1"
    )
    audit("k8s_exec", f"pod={pod} ns={namespace} cmd={command}", result)
    return result


@mcp.tool()
def k8s_microk8s_status() -> str:
    """Show MicroK8s cluster status and enabled addons."""
    result = run(f"{MICROK8S} status 2>&1")
    audit("k8s_microk8s_status", "", result)
    return result


@mcp.tool()
def k8s_enable_addon(addon: str) -> str:
    """Enable a MicroK8s addon (e.g. metrics-server, metallb, cert-manager)."""
    result = run(f"sudo {MICROK8S} enable {addon} 2>&1")
    audit("k8s_enable_addon", addon, result)
    return result


@mcp.tool()
def k8s_disable_addon(addon: str, confirm: bool = False) -> str:
    """Disable a MicroK8s addon. REQUIRES confirm=true."""
    err = require_confirm(confirm, f"disable addon {addon}")
    if err:
        audit("k8s_disable_addon", addon, err, "blocked")
        return err
    result = run(f"sudo {MICROK8S} disable {addon} 2>&1")
    audit("k8s_disable_addon", addon, result)
    return result


@mcp.tool()
def sys_info() -> str:
    """Get a full system overview: OS, kernel, CPU, memory, disk, uptime, load."""
    result = run(
        "echo '=== OS ==='; cat /etc/os-release | head -3; "
        "echo '=== Kernel ==='; uname -r; "
        "echo '=== Uptime ==='; uptime; "
        "echo '=== CPU ==='; nproc; grep 'model name' /proc/cpuinfo | head -1; "
        "echo '=== Memory ==='; free -h; "
        "echo '=== Disk ==='; df -h / /boot /media-pool /downloading 2>/dev/null; "
        "echo '=== Load ==='; cat /proc/loadavg"
    )
    audit("sys_info", "", result)
    return result


@mcp.tool()
def sys_services(state: str = "running") -> str:
    """List systemd services. state can be: running, failed, all."""
    if state == "failed":
        result = run("systemctl list-units --type=service --state=failed --no-pager")
    elif state == "all":
        result = run("systemctl list-units --type=service --no-pager | head -40")
    else:
        result = run("systemctl list-units --type=service --state=running --no-pager | head -40")
    audit("sys_services", f"state={state}", result)
    return result


@mcp.tool()
def sys_service_control(
    service: str, action: str, confirm: bool = False
) -> str:
    """Control a systemd service. action: start, stop, restart, reload, enable, disable.
    stop and disable REQUIRE confirm=true."""
    dangerous = {"stop", "disable"}
    if action in dangerous:
        err = require_confirm(confirm, f"{action} service {service}")
        if err:
            audit("sys_service_control", f"{action} {service}", err, "blocked")
            return err
    result = run(f"sudo systemctl {action} {service} 2>&1")
    audit("sys_service_control", f"{action} {service}", result)
    return result


@mcp.tool()
def sys_service_status(service: str) -> str:
    """Get the status of a systemd service."""
    result = run(f"systemctl status {service} --no-pager 2>&1")
    audit("sys_service_status", service, result)
    return result


@mcp.tool()
def sys_logs(
    service: str = "", lines: int = 50, priority: str = ""
) -> str:
    """Get journalctl logs. Optionally filter by service name and priority (err, warning, info)."""
    svc = f"-u {service}" if service else ""
    pri = f"-p {priority}" if priority else ""
    result = run(
        f"sudo journalctl {svc} {pri} -n {lines} --no-pager 2>&1"
    )
    audit("sys_logs", f"service={service or 'all'} lines={lines} priority={priority or 'all'}", result)
    return result


@mcp.tool()
def sys_updates() -> str:
    """Check for available system package updates (apt + snap)."""
    apt_result = run("apt list --upgradable 2>/dev/null | head -30")
    snap_result = run("snap refresh --list 2>&1")
    result = f"=== APT Updates ===\n{apt_result}\n\n=== Snap Updates ===\n{snap_result}"
    audit("sys_updates", "", result)
    return result


@mcp.tool()
def sys_upgrade(confirm: bool = False) -> str:
    """Upgrade all system packages (apt + snap). REQUIRES confirm=true."""
    err = require_confirm(confirm, "full system upgrade (apt + snap)")
    if err:
        audit("sys_upgrade", "", err, "blocked")
        return err
    apt_result = run("sudo apt-get update -qq 2>&1 && sudo apt-get upgrade -y 2>&1 | tail -20", timeout=300)
    snap_result = run("sudo snap refresh 2>&1")
    result = f"=== APT Upgrade ===\n{apt_result}\n\n=== Snap Refresh ===\n{snap_result}"
    audit("sys_upgrade", "", result)
    return result


@mcp.tool()
def sys_processes(sort_by: str = "cpu", limit: int = 15) -> str:
    """List top processes. sort_by: cpu or mem."""
    order = "-%cpu" if sort_by == "cpu" else "-%mem"
    result = run(f"ps aux --sort={order} | head -{limit + 1}")
    audit("sys_processes", f"sort={sort_by} limit={limit}", result)
    return result


@mcp.tool()
def sys_network() -> str:
    """Show network interfaces, IP addresses, and listening ports."""
    result = run(
        "echo '=== Interfaces ==='; ip -br addr; "
        "echo '=== Listening Ports ==='; ss -tlnp 2>/dev/null | head -25; "
        "echo '=== Routes ==='; ip route | head -10"
    )
    audit("sys_network", "", result)
    return result


@mcp.tool()
def sys_disk() -> str:
    """Show detailed disk usage and mount points."""
    result = run("df -h; echo '---'; lsblk -f 2>/dev/null | head -20")
    audit("sys_disk", "", result)
    return result


@mcp.tool()
def sys_reboot(confirm: bool = False) -> str:
    """Reboot the server. REQUIRES confirm=true."""
    err = require_confirm(confirm, "reboot server")
    if err:
        audit("sys_reboot", "", err, "blocked")
        return err
    audit("sys_reboot", "", "reboot initiated")
    run("sudo reboot")
    return "Reboot command sent. Server will restart."


@mcp.tool()
def sys_shutdown(confirm: bool = False) -> str:
    """Shut down the server. REQUIRES confirm=true."""
    err = require_confirm(confirm, "shutdown server")
    if err:
        audit("sys_shutdown", "", err, "blocked")
        return err
    audit("sys_shutdown", "", "shutdown initiated")
    run("sudo shutdown now")
    return "Shutdown command sent."


@mcp.tool()
def sys_snap_list() -> str:
    """List all installed snap packages."""
    result = run("snap list 2>&1")
    audit("sys_snap_list", "", result)
    return result


@mcp.tool()
def sys_apt_install(package: str, confirm: bool = False) -> str:
    """Install a package via apt. REQUIRES confirm=true."""
    err = require_confirm(confirm, f"apt install {package}")
    if err:
        audit("sys_apt_install", package, err, "blocked")
        return err
    result = run(f"sudo apt-get install -y {package} 2>&1 | tail -15", timeout=120)
    audit("sys_apt_install", package, result)
    return result


@mcp.tool()
def sys_apt_remove(package: str, confirm: bool = False) -> str:
    """Remove a package via apt. REQUIRES confirm=true."""
    err = require_confirm(confirm, f"apt remove {package}")
    if err:
        audit("sys_apt_remove", package, err, "blocked")
        return err
    result = run(f"sudo apt-get remove -y {package} 2>&1 | tail -15", timeout=120)
    audit("sys_apt_remove", package, result)
    return result


@mcp.tool()
def file_read(path: str, max_lines: int = 200) -> str:
    """Read a file from the server. Path must be within allowed directories."""
    if not check_safe_path(path):
        result = f"ERROR: path '{path}' is outside allowed directories."
        audit("file_read", path, result, "blocked")
        return result
    if not os.path.isfile(path):
        return f"ERROR: '{path}' is not a file or does not exist."
    result = run(f"head -{max_lines} '{path}' 2>&1")
    audit("file_read", path, result)
    return result


@mcp.tool()
def file_write(path: str, content: str, confirm: bool = False) -> str:
    """Write content to a file on the server. REQUIRES confirm=true.
    Path must be within allowed directories."""
    if not check_safe_path(path):
        result = f"ERROR: path '{path}' is outside allowed directories."
        audit("file_write", path, result, "blocked")
        return result
    err = require_confirm(confirm, f"write to {path}")
    if err:
        audit("file_write", path, err, "blocked")
        return err
    parent = os.path.dirname(path)
    if parent:
        run(f"sudo mkdir -p '{parent}'")
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False) as f:
        f.write(content)
        tmp = f.name
    result = run(f"sudo cp '{tmp}' '{path}' && sudo chmod 644 '{path}' 2>&1")
    os.unlink(tmp)
    audit("file_write", f"{path} ({len(content)} bytes)", result)
    return result


@mcp.tool()
def file_list(path: str = "/", max_entries: int = 50) -> str:
    """List directory contents."""
    if not check_safe_path(path):
        result = f"ERROR: path '{path}' is outside allowed directories."
        audit("file_list", path, result, "blocked")
        return result
    result = run(f"ls -la '{path}' 2>&1 | head -{max_entries}")
    audit("file_list", path, result)
    return result


@mcp.tool()
def file_find(path: str, pattern: str, max_results: int = 30) -> str:
    """Find files matching a pattern within a directory."""
    if not check_safe_path(path):
        result = f"ERROR: path '{path}' is outside allowed directories."
        audit("file_find", f"{path} {pattern}", result, "blocked")
        return result
    result = run(
        f"find '{path}' -name '{pattern}' -not -path '*/node_modules/*' 2>/dev/null | head -{max_results}"
    )
    audit("file_find", f"{path} pattern={pattern}", result)
    return result


@mcp.tool()
def audit_log(lines: int = 30) -> str:
    """Show recent entries from the audit log."""
    result = run(f"tail -{lines} {AUDIT_LOG} 2>&1")
    return result


@mcp.tool()
def server_info() -> str:
    """Show information about this MCP server: version, uptime, tool count."""
    tools = [
        "k8s_pods", "k8s_deployments", "k8s_services", "k8s_describe",
        "k8s_logs", "k8s_events", "k8s_nodes", "k8s_apply", "k8s_delete",
        "k8s_scale", "k8s_restart", "k8s_rollout_status", "k8s_get_yaml",
        "k8s_namespaces", "k8s_resource_usage", "k8s_exec",
        "k8s_microk8s_status", "k8s_enable_addon", "k8s_disable_addon",
        "sys_info", "sys_services", "sys_service_control", "sys_service_status",
        "sys_logs", "sys_updates", "sys_upgrade", "sys_processes",
        "sys_network", "sys_disk", "sys_reboot", "sys_shutdown",
        "sys_snap_list", "sys_apt_install", "sys_apt_remove",
        "file_read", "file_write", "file_list", "file_find",
        "audit_log", "server_info",
    ]
    result = (
        f"Service Terminal MCP Server\n"
        f"============================\n"
        f"Host: {HOST}:{PORT}\n"
        f"Transport: SSE\n"
        f"Kubectl: {KUBECTL}\n"
        f"Authentication: Bearer token (set SERVICE_TERMINAL_TOKEN env var)\n"
        f"Tools available: {len(tools)}\n\n"
        f"Cluster tools ({sum(1 for t in tools if t.startswith('k8s_'))}):\n"
        + "\n".join(f"  - {t}" for t in tools if t.startswith("k8s_"))
        + f"\n\nSystem tools ({sum(1 for t in tools if t.startswith('sys_'))}):\n"
        + "\n".join(f"  - {t}" for t in tools if t.startswith("sys_"))
        + f"\n\nFile tools ({sum(1 for t in tools if t.startswith('file_'))}):\n"
        + "\n".join(f"  - {t}" for t in tools if t.startswith("file_"))
        + f"\n\nMeta tools ({sum(1 for t in tools if t in ('audit_log', 'server_info'))}):\n"
        + "\n".join(f"  - {t}" for t in tools if t in ("audit_log", "server_info"))
    )
    return result


if __name__ == "__main__":
    if BEARER_TOKEN:
        logger.info("Starting Service Terminal MCP Server on %s:%d (SSE transport) with Bearer token authentication", HOST, PORT)
    else:
        logger.warning("Starting Service Terminal MCP Server on %s:%d (SSE transport) WITHOUT authentication - set SERVICE_TERMINAL_TOKEN env var", HOST, PORT)
    audit("server", "startup", f"MCP server started on {HOST}:{PORT} with auth={'enabled' if BEARER_TOKEN else 'disabled'}")
    mcp.run(transport="sse")