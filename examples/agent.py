#!/usr/bin/env python3
"""
Jarvis MCP Agent — Connect Mistral's LLM to your MCP server.

This script runs an agent loop:
  1. You type a natural language prompt
  2. The prompt + available tools are sent to Mistral's API
  3. The LLM decides which tools to call
  4. Tool calls are executed via the MCP server (through SSH tunnel)
  5. Results are fed back to the LLM
  6. Repeat until the LLM gives a final answer

Prerequisites:
    pip install mcp mistralai

    # Set your Mistral API key:
    export MISTRAL_API_KEY="your-api-key-here"

    # Create SSH tunnel to the server (keep this running):
    ssh -L 8080:localhost:8080 worker@192.168.1.107

Usage:
    # Interactive chat mode:
    python agent.py

    # Single prompt:
    python agent.py "Show me all pods in the arr namespace and check system load"

    # Use a different model:
    python agent.py --model mistral-large-latest

    # Use a different MCP URL (e.g. direct LAN access):
    python agent.py --url http://192.168.1.107:8080/sse
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mistralai import Mistral

# ── Configuration ──────────────────────────────────────────────────────────
DEFAULT_MODEL = "mistral-large-latest"
DEFAULT_MCP_URL = "http://localhost:8080/sse"
MAX_ITERATIONS = 15  # Prevent infinite loops

SYSTEM_PROMPT = """You are Jarvis Admin, an AI assistant that manages an Ubuntu server \
and its MicroK8s Kubernetes cluster. You have access to 40 tools for:

- Cluster management: list pods, deployments, services, apply manifests, \
scale, restart, delete resources, get logs, manage addons
- System management: check system info, services, disk, network, processes, \
updates, reboot
- File operations: read, write, list, find files

Guidelines:
- Always check the current state before making changes
- Use k8s_apply with dry_run=true first to validate manifests
- Never use destructive operations (delete, reboot, shutdown) without \
explicitly telling the user what you're about to do and why
- When asked about the cluster, check nodes, pods, and events for a full picture
- Be concise in your responses
- When showing data, format it clearly
"""


# ── Tool Conversion ────────────────────────────────────────────────────────
def mcp_tools_to_mistral(mcp_tools: list) -> list[dict]:
    """Convert MCP tool definitions to Mistral API tool format."""
    tools = []
    for t in mcp_tools:
        # Build JSON schema for parameters from the MCP tool's input schema
        properties = {}
        required = []
        if t.inputSchema and "properties" in t.inputSchema:
            properties = t.inputSchema["properties"]
        if t.inputSchema and "required" in t.inputSchema:
            required = t.inputSchema["required"]

        tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or f"Call the {t.name} tool",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
    return tools


# ── Agent Loop ─────────────────────────────────────────────────────────────
async def run_agent(
    session: ClientSession,
    client: Mistral,
    model: str,
    user_prompt: str,
    verbose: bool = True,
) -> str:
    """Run the agent loop: LLM → tool calls → results → LLM → ... → answer."""

    # Get available tools from MCP server
    tools_result = await session.list_tools()
    mistral_tools = mcp_tools_to_mistral(tools_result.tools)

    if verbose:
        print(f"\n[Agent] Connected. {len(mistral_tools)} tools available.")
        print(f"[Agent] Model: {model}")
        print(f"[Agent] Prompt: {user_prompt}\n")

    # Build conversation
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    for iteration in range(MAX_ITERATIONS):
        if verbose:
            print(f"[Agent] Iteration {iteration + 1}/{MAX_ITERATIONS} — calling LLM...")

        # Call Mistral API with tool definitions
        response = client.chat.complete(
            model=model,
            messages=messages,
            tools=mistral_tools,
            tool_choice="auto",
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        # Check if the LLM wants to call tools
        if not assistant_message.tool_calls:
            # No tool calls — this is the final answer
            final_text = assistant_message.content or ""
            if verbose:
                print(f"\n{'='*60}")
                print("  Final Answer")
                print(f"{'='*60}\n")
            return final_text

        # Execute each tool call
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            if verbose:
                args_preview = json.dumps(tool_args)[:120]
                print(f"[Agent] 🔧 Calling: {tool_name}({args_preview})")

            # Execute via MCP
            try:
                result = await session.call_tool(tool_name, tool_args)
                # Extract text content from MCP result
                result_text = "\n".join(
                    c.text for c in result.content if hasattr(c, "text")
                )
                # Truncate very long results
                if len(result_text) > 8000:
                    result_text = result_text[:8000] + "\n... (truncated)"

                if verbose:
                    preview = result_text[:200].replace("\n", " | ")
                    print(f"[Agent]    → {preview}...")

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": result_text,
                })

            except Exception as e:
                error_msg = f"Error calling {tool_name}: {str(e)}"
                if verbose:
                    print(f"[Agent]    ✗ {error_msg}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": error_msg,
                })

    return "Maximum iterations reached. The agent may need more steps to complete the task."


# ── Interactive Chat ───────────────────────────────────────────────────────
async def interactive_chat(
    session: ClientSession,
    client: Mistral,
    model: str,
) -> None:
    """Interactive REPL: type prompts, get LLM-powered responses."""
    print(f"\n{'='*60}")
    print("  Jarvis MCP Agent — Interactive Mode")
    print(f"  Model: {model}")
    print(f"  MCP Server: connected")
    print(f"{'='*60}")
    print("  Type your request in natural language.")
    print("  Examples:")
    print("    - Show me all running pods")
    print("    - What's the system load and disk usage?")
    print("    - Restart the jellyfin deployment in the arr namespace")
    print("    - Check for system updates")
    print("    - List files in /opt/jarvis-mcp")
    print("  Type 'quit' or 'exit' to stop.")
    print(f"{'='*60}\n")

    while True:
        try:
            prompt = input("you> ").strip()
            if prompt.lower() in ("quit", "exit", "q"):
                break
            if not prompt:
                continue

            answer = await run_agent(session, client, model, prompt)
            print(f"\njarvis> {answer}\n")

        except KeyboardInterrupt:
            print("\nUse 'quit' to exit.")
        except Exception as e:
            print(f"\nError: {e}\n")


# ── Main ───────────────────────────────────────────────────────────────────
async def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis MCP Agent — Mistral LLM + MCP Server")
    parser.add_argument("prompt", nargs="?", help="Single prompt to send (omit for interactive mode)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Mistral model (default: {DEFAULT_MODEL})")
    parser.add_argument("--url", default=DEFAULT_MCP_URL, help=f"MCP SSE URL (default: {DEFAULT_MCP_URL})")
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY environment variable not set.")
        print("Get your key at: https://console.mistral.ai/api-keys/")
        print("Then run: export MISTRAL_API_KEY='your-key-here'")
        sys.exit(1)

    client = Mistral(api_key=api_key)

    print(f"Connecting to MCP server at {args.url} ...")

    async with sse_client(args.url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected to MCP server!")

            if args.prompt:
                # Single prompt mode
                answer = await run_agent(session, client, args.model, args.prompt)
                print(f"\n{answer}")
            else:
                # Interactive mode
                await interactive_chat(session, client, args.model)


if __name__ == "__main__":
    asyncio.run(main())
