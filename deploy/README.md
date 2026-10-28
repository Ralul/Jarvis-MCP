# Service Terminal MCP Server — Deployment

## Quick Deployment

```bash
# Clone and deploy
sudo bash deploy.sh
```

## Configuration Options

### Authentication

The server supports Bearer token authentication via the `SERVICE_TERMINAL_TOKEN` environment variable.

**To set the token:**

1. **Temporary (for testing):**
   ```bash
   export SERVICE_TERMINAL_TOKEN="your-secure-token-here"
   python server/server.py
   ```

2. **Persistent (systemd service):**
   ```bash
   sudo systemctl edit service-terminal
   # Add the following:
   [Service]
   Environment="SERVICE_TERMINAL_TOKEN=your-secure-token-here"
   
   # Then reload and restart:
   sudo systemctl daemon-reload
   sudo systemctl restart service-terminal
   ```

### Custom Installation Paths

Edit `deploy.sh` before running:
- `INSTALL_DIR`: Where server files are installed (default: `/opt/service-terminal`)
- `LOG_DIR`: Where logs are stored (default: `/var/log/service-terminal`)
- `SERVICE_NAME`: Systemd service name (default: `service-terminal`)
- `TARGET_USER`: User to run the service (default: `worker`)

### Network Configuration

The server binds to `127.0.0.1:8080` by default for security. To expose it:

1. **Use a reverse proxy (recommended):**
   ```bash
   # Nginx example
   sudo apt install nginx
   sudo nano /etc/nginx/sites-available/service-terminal
   # Add configuration to proxy_pass to http://127.0.0.1:8080/sse
   sudo ln -s /etc/nginx/sites-available/service-terminal /etc/nginx/sites-enabled/
   sudo systemctl restart nginx
   ```

2. **Or bind to all interfaces (not recommended):**
   Edit `server/server.py` and change:
   ```python
   HOST = "127.0.0.1"
   # to
   HOST = "0.0.0.0"
   ```

## Files Created

| File | Purpose |
|------|---------|
| `/opt/service-terminal/server.py` | MCP server script |
| `/opt/service-terminal/venv/` | Python virtual environment |
| `/etc/systemd/system/service-terminal.service` | Systemd service unit |
| `/etc/sudoers.d/service-terminal` | Sudo permissions |
| `/var/log/service-terminal/` | Audit and server logs |

## Service Management

```bash
# Start/stop/restart
sudo systemctl start service-terminal
sudo systemctl stop service-terminal
sudo systemctl restart service-terminal

# Enable on boot
sudo systemctl enable service-terminal

# View logs
sudo journalctl -u service-terminal -f

# View audit log
tail -f /var/log/service-terminal/audit.log

# Check status
sudo systemctl status service-terminal
```

## Requirements

- Ubuntu 22.04+ (tested on 26.04)
- MicroK8s installed: `sudo snap install microk8s --classic`
- Python 3.10+ with `python3-venv`
- User with sudo access

## Troubleshooting

### Server fails to start

```bash
sudo journalctl -u service-terminal -n 50
```

### Permission errors

Ensure the `worker` user is in the `microk8s` group:
```bash
sudo usermod -a -G microk8s worker
```

### Connection refused

Check the server is running:
```bash
curl -v http://127.0.0.1:8080/sse
```

### Authentication errors

Verify the token is set correctly in the systemd service:
```bash
sudo systemctl show service-terminal -p Environment
```
