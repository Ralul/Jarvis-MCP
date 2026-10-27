#!/usr/bin/env python3
"""
Jarvis Agent Service
====================
A web-based AI agent that runs on the server itself and connects to the
local MCP server (no SSH tunnel needed). Provides a chat UI accessible
from any browser on the LAN.

Architecture:
    Browser ──HTTP──► Agent Service (:8081) ──MCP/SSE──► MCP Server (:8080)
                           │                                    │
                           └──► Mistral API (cloud)            └──► kubectl, systemd, files

Endpoints:
    GET  /           → Chat web UI
    POST /chat       → Send a message, get AI response (JSON: {"message": "...", "session_id": "..."})
    GET  /health     → Health check
    GET  /tools      → List available MCP tools
    POST /reset      → Reset a conversation session

Configuration:
    MISTRAL_API_KEY  → Mistral API key (required, set in env or /opt/jarvis-mcp/agent.env)
    AGENT_MODEL      → Mistral model (default: mistral-large-latest)
    AGENT_API_KEY    → Optional API key to protect the chat endpoint
    MCP_URL          → MCP server SSE URL (default: http://127.0.0.1:8080/sse)
    AGENT_PORT       → Port to listen on (default: 8081)

Usage:
    # Direct:
    MISTRAL_API_KEY=xxx python agent_service.py

    # As a service:
    sudo systemctl start jarvis-agent
"""

import asyncio
import json
import os
import uuid
from contextlib import AsyncExitStack
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from mcp import ClientSession
from mcp.client.sse import sse_client
from mistralai import Mistral

# ── Configuration ──────────────────────────────────────────────────────────
MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8080/sse")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8081"))
AGENT_MODEL = os.environ.get("AGENT_MODEL", "mistral-large-latest")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "")  # Optional: protect the API
MAX_ITERATIONS = 15

# ── System Prompt ──────────────────────────────────────────────────────────
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
- When showing data, format it clearly with markdown
- The server hostname is 'jarvis' at 192.168.1.107
"""

# ── Global State ───────────────────────────────────────────────────────────
app = FastAPI(title="Jarvis Agent", version="1.0.0")

_mcp_stack: Optional[AsyncExitStack] = None
_mcp_session: Optional[ClientSession] = None
_mistral_client: Optional[Mistral] = None
_conversations: dict[str, list[dict]] = {}  # session_id → message history


# ── MCP Connection Management ──────────────────────────────────────────────
async def connect_mcp():
    """Establish persistent MCP connection on startup."""
    global _mcp_stack, _mcp_session
    _mcp_stack = AsyncExitStack()
    read, write = await _mcp_stack.enter_async_context(sse_client(MCP_URL))
    _mcp_session = await _mcp_stack.enter_async_context(ClientSession(read, write))
    await _mcp_session.initialize()
    tools = await _mcp_session.list_tools()
    print(f"[Agent] Connected to MCP server at {MCP_URL} — {len(tools.tools)} tools available")


async def disconnect_mcp():
    """Close MCP connection on shutdown."""
    global _mcp_stack
    if _mcp_stack:
        await _mcp_stack.aclose()
        print("[Agent] MCP connection closed")


@app.on_event("startup")
async def startup():
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        # Try loading from env file
        env_file = "/opt/jarvis-mcp/agent.env"
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("MISTRAL_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        os.environ["MISTRAL_API_KEY"] = api_key
                        break

    if not api_key:
        print("[Agent] WARNING: MISTRAL_API_KEY not set. Chat will not work.")
    else:
        global _mistral_client
        _mistral_client = Mistral(api_key=api_key)
        print(f"[Agent] Mistral client initialized (model: {AGENT_MODEL})")

    try:
        await connect_mcp()
    except Exception as e:
        print(f"[Agent] WARNING: Failed to connect to MCP server: {e}")
        print("[Agent] Will retry on first chat request.")


@app.on_event("shutdown")
async def shutdown():
    await disconnect_mcp()


# ── Helpers ────────────────────────────────────────────────────────────────
def check_api_key(authorization: Optional[str] = Header(None)):
    """Optional API key check."""
    if not AGENT_API_KEY:
        return
    if authorization != f"Bearer {AGENT_API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key")


def mcp_tools_to_mistral(mcp_tools: list) -> list[dict]:
    """Convert MCP tool definitions to Mistral API tool format."""
    tools = []
    for t in mcp_tools:
        properties = {}
        required = []
        if t.inputSchema:
            properties = t.inputSchema.get("properties", {})
            required = t.inputSchema.get("required", [])
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


async def ensure_mcp_connected():
    """Ensure MCP connection is alive, reconnect if needed."""
    global _mcp_session
    if _mcp_session is None:
        await connect_mcp()


# ── Request/Response Models ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[str]


# ── Agent Loop ─────────────────────────────────────────────────────────────
async def run_agent_loop(user_message: str, session_id: str) -> tuple[str, list[str]]:
    """Run the agent loop for a single user message."""
    global _mistral_client, _mcp_session

    if _mistral_client is None:
        raise HTTPException(status_code=503, detail="Mistral API key not configured")

    await ensure_mcp_connected()

    # Get tools
    tools_result = await _mcp_session.list_tools()
    mistral_tools = mcp_tools_to_mistral(tools_result.tools)

    # Get or create conversation history
    if session_id not in _conversations:
        _conversations[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages = _conversations[session_id]
    messages.append({"role": "user", "content": user_message})

    tool_calls_made = []

    for iteration in range(MAX_ITERATIONS):
        response = _mistral_client.chat.complete(
            model=AGENT_MODEL,
            messages=messages,
            tools=mistral_tools,
            tool_choice="auto",
        )

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        if not assistant_message.tool_calls:
            # Final answer
            final_text = assistant_message.content or ""
            # Trim conversation history to prevent unbounded growth
            if len(messages) > 30:
                _conversations[session_id] = [messages[0]] + messages[-20:]
            return final_text, tool_calls_made

        # Execute tool calls
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            tool_calls_made.append(tool_name)
            print(f"[Agent] 🔧 {tool_name}({tool_call.function.arguments[:100]})")

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            try:
                result = await _mcp_session.call_tool(tool_name, tool_args)
                result_text = "\n".join(
                    c.text for c in result.content if hasattr(c, "text")
                )
                if len(result_text) > 8000:
                    result_text = result_text[:8000] + "\n... (truncated)"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": result_text,
                })
            except Exception as e:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": f"Error: {str(e)}",
                })

    return "Maximum iterations reached. Please try a more specific request.", tool_calls_made


# ── API Endpoints ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check endpoint."""
    mcp_connected = _mcp_session is not None
    mistral_configured = _mistral_client is not None
    return {
        "status": "ok" if (mcp_connected and mistral_configured) else "degraded",
        "mcp_connected": mcp_connected,
        "mcp_url": MCP_URL,
        "mistral_configured": mistral_configured,
        "model": AGENT_MODEL,
        "active_sessions": len(_conversations),
    }


@app.get("/tools")
async def list_tools(authorization: Optional[str] = Header(None)):
    """List all available MCP tools."""
    check_api_key(authorization)
    await ensure_mcp_connected()
    tools = await _mcp_session.list_tools()
    return {
        "count": len(tools.tools),
        "tools": [
            {"name": t.name, "description": (t.description or "").split("\n")[0]}
            for t in tools.tools
        ],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, authorization: Optional[str] = Header(None)):
    """Send a message to the AI agent and get a response."""
    check_api_key(authorization)
    session_id = req.session_id or str(uuid.uuid4())
    response_text, tool_calls = await run_agent_loop(req.message, session_id)
    return ChatResponse(response=response_text, session_id=session_id, tool_calls=tool_calls)


@app.post("/reset")
async def reset_session(session_id: str, authorization: Optional[str] = Header(None)):
    """Reset a conversation session."""
    check_api_key(authorization)
    if session_id in _conversations:
        del _conversations[session_id]
    return {"status": "reset", "session_id": session_id}


# ── Web Chat UI ────────────────────────────────────────────────────────────
CHAT_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Jarvis Agent</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9; height: 100vh;
    display: flex; flex-direction: column;
  }
  #header {
    background: #161b22; padding: 12px 20px; border-bottom: 1px solid #30363d;
    display: flex; align-items: center; gap: 10px;
  }
  #header h1 { font-size: 16px; color: #58a6ff; }
  #status { font-size: 12px; color: #8b949e; margin-left: auto; }
  #status.online { color: #3fb950; }
  #status.offline { color: #f85149; }
  #messages {
    flex: 1; overflow-y: auto; padding: 20px;
    max-width: 900px; margin: 0 auto; width: 100%;
  }
  .msg {
    margin-bottom: 16px; padding: 12px 16px; border-radius: 8px;
    max-width: 80%; line-height: 1.5; font-size: 14px;
  }
  .msg.user {
    background: #1f6feb; color: #fff; margin-left: auto;
    border-bottom-right-radius: 2px;
  }
  .msg.agent {
    background: #161b22; border: 1px solid #30363d;
    border-bottom-left-radius: 2px;
  }
  .msg.agent pre {
    background: #0d1117; padding: 8px 12px; border-radius: 4px;
    overflow-x: auto; font-size: 12px; margin: 8px 0;
  }
  .msg.agent code { background: #0d1117; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
  .msg.agent table { border-collapse: collapse; margin: 8px 0; font-size: 12px; }
  .msg.agent th, .msg.agent td { border: 1px solid #30363d; padding: 4px 8px; }
  .msg.agent th { background: #21262d; }
  .tools-used {
    font-size: 11px; color: #8b949e; margin-top: 6px;
    display: flex; flex-wrap: wrap; gap: 4px;
  }
  .tool-badge {
    background: #21262d; border: 1px solid #30363d;
    padding: 2px 8px; border-radius: 10px; font-family: monospace;
  }
  .typing { color: #8b949e; font-style: italic; }
  #input-area {
    padding: 16px 20px; border-top: 1px solid #30363d;
    background: #161b22; display: flex; gap: 10px;
    max-width: 900px; margin: 0 auto; width: 100%;
  }
  #input {
    flex: 1; background: #0d1117; border: 1px solid #30363d;
    color: #c9d1d9; padding: 10px 14px; border-radius: 6px;
    font-size: 14px; outline: none;
  }
  #input:focus { border-color: #58a6ff; }
  #send {
    background: #1f6feb; color: #fff; border: none;
    padding: 10px 20px; border-radius: 6px; cursor: pointer;
    font-size: 14px;
  }
  #send:disabled { opacity: 0.5; cursor: not-allowed; }
  #reset {
    background: #21262d; color: #8b949e; border: 1px solid #30363d;
    padding: 10px 14px; border-radius: 6px; cursor: pointer; font-size: 12px;
  }
</style>
</head>
<body>
<div id="header">
  <h1>🤖 Jarvis Agent</h1>
  <span id="status">connecting...</span>
</div>
<div id="messages"></div>
<div id="input-area">
  <button id="reset" onclick="resetSession()">New Chat</button>
  <input id="input" type="text" placeholder="Ask about your server... (e.g. 'Show all pods')" autofocus>
  <button id="send" onclick="sendMessage()">Send</button>
</div>

<script>
let sessionId = localStorage.getItem('jarvis_session') || crypto.randomUUID();
localStorage.setItem('jarvis_session', sessionId);

const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('input');
const sendBtn = document.getElementById('send');
const statusEl = document.getElementById('status');

// Check health on load
fetch('/health').then(r => r.json()).then(d => {
  if (d.status === 'ok') {
    statusEl.textContent = '● online — ' + d.model;
    statusEl.className = 'online';
  } else {
    statusEl.textContent = '● degraded: MCP=' + d.mcp_connected + ' Mistral=' + d.mistral_configured;
    statusEl.className = 'offline';
  }
}).catch(() => {
  statusEl.textContent = '● offline';
  statusEl.className = 'offline';
});

// Simple markdown rendering
function renderMd(text) {
  return text
    .replace(/```(\\w*)\\n([\\s\\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\n/g, '<br>');
}

function addMessage(text, isUser, toolsUsed) {
  const div = document.createElement('div');
  div.className = 'msg ' + (isUser ? 'user' : 'agent');
  div.innerHTML = isUser ? escapeHtml(text) : renderMd(text);
  if (toolsUsed && toolsUsed.length > 0) {
    const toolsDiv = document.createElement('div');
    toolsDiv.className = 'tools-used';
    toolsUsed.forEach(t => {
      const badge = document.createElement('span');
      badge.className = 'tool-badge';
      badge.textContent = t;
      toolsDiv.appendChild(badge);
    });
    div.appendChild(toolsDiv);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function addTyping() {
  const div = document.createElement('div');
  div.className = 'msg agent typing';
  div.id = 'typing-indicator';
  div.textContent = 'Thinking...';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  sendBtn.disabled = true;
  addMessage(text, true);
  addTyping();

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text, session_id: sessionId})
    });
    const data = await res.json();
    removeTyping();
    if (data.response) {
      addMessage(data.response, false, data.tool_calls);
    } else {
      addMessage('Error: ' + (data.detail || 'Unknown error'), false);
    }
  } catch (e) {
    removeTyping();
    addMessage('Connection error: ' + e.message, false);
  }

  sendBtn.disabled = false;
  inputEl.focus();
}

async function resetSession() {
  sessionId = crypto.randomUUID();
  localStorage.setItem('jarvis_session', sessionId);
  await fetch('/reset?session_id=' + sessionId, {method: 'POST'});
  messagesEl.innerHTML = '';
}

inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter') sendMessage();
});
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def chat_ui():
    """Serve the chat web UI."""
    return CHAT_UI


# ── Run ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print(f"[Agent] Starting Jarvis Agent Service on 0.0.0.0:{AGENT_PORT}")
    print(f"[Agent] MCP server: {MCP_URL}")
    print(f"[Agent] Model: {AGENT_MODEL}")
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT, log_level="info")
