#!/usr/bin/env bash
# =============================================================================
# tunnel.sh — Create an SSH tunnel to the Jarvis MCP server
# =============================================================================
# Usage:
#   ./tunnel.sh [user@host]
#
# Default: worker@192.168.1.107
# After running, the MCP server is available at http://localhost:8080/sse
# Keep this terminal open while using the agent.
# =============================================================================

TARGET="${1:-worker@192.168.1.107}"

echo "Creating SSH tunnel to $TARGET ..."
echo "MCP server will be available at: http://localhost:8080/sse"
echo "Press Ctrl+C to close the tunnel."
echo ""

ssh -L 8080:localhost:8080 -N "$TARGET"
