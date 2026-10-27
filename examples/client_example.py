#!/usr/bin/env python3
"""
Example MCP client for the Jarvis Admin Server.

This script connects to the MCP server via SSE and demonstrates
how to call tools. Use it as a starting point for building your
own LLM-powered admin client.

Prerequisites:
    pip install mcp

Usage:
    # First, create an SSH tunnel to the server:
    ssh -L 8080:localhost:8080 worker@192.168.1.107

    # Then run this script:
    python client_example.py
"""

import asyncio
import sys
from mcp import ClientSession
from mcp.client.sse import sse_client

MCP_URL = "http://localhost:8080/sse"


async def list_tools(session: ClientSession) -> None:
    """List all available tools on the server."""
    tools = await session.list_tools()
    print(f"\n{'='*60}")
    print(f"  Available Tools ({len(tools.tools)})")
    print(f"{'='*60}")
    for t in tools.tools:
        desc = (t.description or "").split("\n")[0][:70]
        print(f"  {t.name:30s}  {desc}")


async def call(session: ClientSession, tool: str, args: dict | None = None) -> str:
    """Call a tool and return its text output."""
    result = await session.call_tool(tool, args or {})
    return "\n".join(c.text for c in result.content if hasattr(c, "text"))


async def demo_cluster_ops(session: ClientSession) -> None:
    """Demonstrate cluster management tools."""
    print(f"\n{'='*60}")
    print("  Cluster Operations Demo")
    print(f"{'='*60}")

    print("\n--- Nodes ---")
    print(await call(session, "k8s_nodes"))

    print("\n--- Pods (all namespaces) ---")
    print(await call(session, "k8s_pods", {"all_namespaces": True}))

    print("\n--- Deployments (arr namespace) ---")
    print(await call(session, "k8s_deployments", {"namespace": "arr"}))

    print("\n--- Services (all namespaces) ---")
    print(await call(session, "k8s_services", {"all_namespaces": True}))

    print("\n--- MicroK8s Status ---")
    print(await call(session, "k8s_microk8s_status"))


async def demo_system_ops(session: ClientSession) -> None:
    """Demonstrate system management tools."""
    print(f"\n{'='*60}")
    print("  System Operations Demo")
    print(f"{'='*60}")

    print("\n--- System Info ---")
    print(await call(session, "sys_info"))

    print("\n--- Disk Usage ---")
    print(await call(session, "sys_disk"))

    print("\n--- Top Processes (by CPU) ---")
    print(await call(session, "sys_processes", {"sort_by": "cpu", "limit": 5}))

    print("\n--- Failed Services ---")
    print(await call(session, "sys_services", {"state": "failed"}))


async def demo_safety(session: ClientSession) -> None:
    """Demonstrate safety guardrails."""
    print(f"\n{'='*60}")
    print("  Safety Guardrails Demo")
    print(f"{'='*60}")

    print("\n--- Try to delete a pod WITHOUT confirm (should be blocked) ---")
    result = await call(session, "k8s_delete", {
        "resource_type": "pod",
        "name": "jellyfin-test",
        "namespace": "arr",
        "confirm": False,
    })
    print(result)

    print("\n--- Try to reboot WITHOUT confirm (should be blocked) ---")
    result = await call(session, "sys_reboot", {"confirm": False})
    print(result)

    print("\n--- k8s_apply with dry_run=true (safe) ---")
    manifest = """
apiVersion: v1
kind: ConfigMap
metadata:
  name: test-config
  namespace: default
data:
  key: value
"""
    result = await call(session, "k8s_apply", {"manifest": manifest, "dry_run": True})
    print(result)


async def interactive_mode(session: ClientSession) -> None:
    """Simple interactive REPL for calling tools."""
    print(f"\n{'='*60}")
    print("  Interactive Mode")
    print("  Type a tool name and JSON args, or 'quit' to exit.")
    print("  Example: k8s_pods {\"namespace\": \"arr\"}")
    print(f"{'='*60}")

    import json

    while True:
        try:
            line = input("\nmcp> ").strip()
            if line.lower() in ("quit", "exit", "q"):
                break
            if not line:
                continue

            parts = line.split(" ", 1)
            tool = parts[0]
            args = json.loads(parts[1]) if len(parts) > 1 else {}

            result = await call(session, tool, args)
            print(result[:2000])
        except json.JSONDecodeError:
            print("Invalid JSON args. Example: k8s_pods {\"namespace\": \"arr\"}")
        except Exception as e:
            print(f"Error: {e}")


async def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Jarvis MCP Client Example")
    parser.add_argument("--url", default=MCP_URL, help=f"MCP SSE URL (default: {MCP_URL})")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive REPL mode")
    args = parser.parse_args()

    print(f"Connecting to {args.url} ...")

    async with sse_client(args.url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected!")

            await list_tools(session)

            if args.interactive:
                await interactive_mode(session)
            else:
                await demo_cluster_ops(session)
                await demo_system_ops(session)
                await demo_safety(session)

            # Show audit log
            print(f"\n{'='*60}")
            print("  Recent Audit Log")
            print(f"{'='*60}")
            print(await call(session, "audit_log", {"lines": 10}))

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
