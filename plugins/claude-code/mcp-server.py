#!/usr/bin/env python3
"""Pegify MCP Channel Server — pushes messages into Claude Code sessions.

This is a minimal MCP server that:
1. Declares the claude/channel capability (makes Claude Code keep the session alive)
2. Polls the Pegify daemon for new messages across ALL subscribed channels
3. Queues messages with priority tagging (mention vs channel) and delivers as batch
4. Exposes tools (reply, read_channel, list_agents, list_channels, check_messages)

Runs as a subprocess of Claude Code via .mcp.json. Uses only stdlib — no extra deps.
"""

import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

# --- Configuration ---

DAEMON_URL = os.environ.get("PEGIFY_DAEMON_URL", "http://127.0.0.1:7654")
POLL_INTERVAL = float(os.environ.get("PEGIFY_POLL_INTERVAL", "2"))  # seconds

# --- Resolve agent identity ---

def resolve_identity() -> dict:
    """Resolve Pegify identity from project config or session file."""
    # 1. From environment (headless sessions)
    display_name = os.environ.get("PEGIFY_DISPLAY_NAME")
    if display_name:
        return {"agent": display_name, "channel": os.environ.get("PEGIFY_CHANNEL", "my-team")}

    # 2. From project .pegify.yaml
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        config_path = Path(project_dir) / ".pegify.yaml"
        if config_path.exists():
            try:
                import yaml
                data = yaml.safe_load(config_path.read_text())
                if data and "agent" in data:
                    company = data.get("company", "")
                    result = dict(data)
                    if company:
                        result["company"] = company
                    return result
            except Exception:
                pass

    # 3. From session identity files (written by session-start hook)
    pegify_home = Path(os.environ.get("PEGIFY_HOME", Path.home() / ".pegify"))
    session_dir = pegify_home / "sessions"
    if session_dir.exists():
        for f in sorted(session_dir.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.name.startswith("_"):
                continue  # skip marker files
            try:
                import yaml
                data = yaml.safe_load(f.read_text())
                if data and "display_name" in data:
                    channel = data.get("channel", "")
                    # Fall back to .pegify.yaml channel if session file is missing it
                    if not channel:
                        try:
                            _proj = os.environ.get("CLAUDE_PROJECT_DIR", "")
                            if _proj:
                                _cfg = Path(_proj) / ".pegify.yaml"
                                if _cfg.exists():
                                    channel = yaml.safe_load(_cfg.read_text()).get("channel", "")
                        except Exception:
                            pass
                    result = {"agent": data["display_name"], "channel": channel}
                    if data.get("session_id"):
                        result["session_id"] = data["session_id"]
                    return result
            except Exception:
                continue

    # 4. Global default
    default_id = pegify_home / ".default-identity"
    if default_id.exists():
        try:
            import yaml
            return yaml.safe_load(default_id.read_text()) or {}
        except Exception:
            pass

    # Last resort — no identity found. Channel must come from config.
    return {"agent": "claude", "channel": ""}


def resolve_subscriptions(identity: dict) -> dict:
    """Resolve channel subscriptions from config. Returns {channel: mode}."""
    subs = identity.get("subscriptions", {})
    primary = identity.get("channel", "")
    if not subs:
        subs = {primary: "active"}
    if primary not in subs:
        subs[primary] = "active"
    return subs


# --- stdout/stdin I/O with thread safety ---

_write_lock = threading.Lock()
_request_id_counter = 0


def _next_id() -> int:
    global _request_id_counter
    _request_id_counter += 1
    return _request_id_counter


def write_message(msg: dict):
    """Thread-safe write a JSON-RPC message to stdout."""
    with _write_lock:
        line = json.dumps(msg)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def write_notification(method: str, params: dict):
    """Write a JSON-RPC notification (no id, no response expected)."""
    write_message({"jsonrpc": "2.0", "method": method, "params": params})


def write_response(result, req_id):
    """Write a JSON-RPC success response."""
    write_message({"jsonrpc": "2.0", "result": result, "id": req_id})


def write_error(code: int, message: str, req_id):
    """Write a JSON-RPC error response."""
    write_message({"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": req_id})


# --- Daemon HTTP helpers ---

def _api_token() -> str:
    """Read daemon API token from ~/.pegify/api-token."""
    token_file = Path.home() / ".pegify" / "api-token"
    if token_file.exists():
        return token_file.read_text().strip()
    return ""


def daemon_get(path: str, timeout: float = 3) -> dict | None:
    """GET request to daemon API."""
    try:
        req = urllib.request.Request(f"{DAEMON_URL}{path}")
        token = _api_token()
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def daemon_post(path: str, body: dict, timeout: float = 3) -> dict | None:
    """POST request to daemon API (expects JSON response)."""
    try:
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        token = _api_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{DAEMON_URL}{path}",
            data=data,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def daemon_post_raw(path: str, body: dict, timeout: float = 5) -> str | None:
    """POST request to daemon API, returns raw text body.

    Used for context endpoints that return text/plain (padded snapshots)
    or application/json that we want to pass through byte-identically
    without re-serializing (preserves cache-friendly byte determinism).
    """
    try:
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        token = _api_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            f"{DAEMON_URL}{path}",
            data=data,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except Exception:
        return None


def auto_checkout(file_path: str):
    """Auto-checkout a file when the agent edits it."""
    identity = resolve_identity()
    agent = identity.get("agent", "unknown")
    channel = identity.get("channel", "")
    project = os.environ.get("CLAUDE_PROJECT_DIR", "")
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    if not project:
        return None
    # Make path relative to project
    try:
        rel_path = os.path.relpath(file_path, project)
    except ValueError:
        rel_path = file_path
    result = daemon_post("/files/checkout", {
        "file": rel_path,
        "project": project,
        "agent": agent,
        "channel": channel,
        "session_id": session_id,
    })
    return result


# --- Message Queue ---

class MessageQueue:
    """Thread-safe in-memory message queue."""

    def __init__(self):
        self._lock = threading.Lock()
        self._queue: list = []

    def push(self, msg: dict):
        with self._lock:
            self._queue.append(msg)

    def drain(self) -> list:
        with self._lock:
            msgs = list(self._queue)
            self._queue.clear()
            return msgs

    def count(self) -> int:
        with self._lock:
            return len(self._queue)


_message_queue = MessageQueue()


# --- MCP Protocol Handlers ---

TOOLS = [
    {
        "name": "reply",
        "description": "Reply to a Pegify channel message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name"},
                "body": {"type": "string", "description": "Message body"},
            },
            "required": ["channel", "body"],
        },
    },
    {
        "name": "read_channel",
        "description": "Read recent messages from a Pegify channel",
        "inputSchema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name"},
                "limit": {"type": "integer", "description": "Max messages", "default": 20},
            },
            "required": ["channel"],
        },
    },
    {
        "name": "list_agents",
        "description": "List online Pegify agents",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_channels",
        "description": "List available Pegify channels",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_messages",
        "description": "Check queued Pegify messages across all subscribed channels",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "checkout_file",
        "description": "Check out a file for exclusive editing. Advisory lock — warns teammates if already locked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path relative to project root"}
            },
            "required": ["file"]
        }
    },
    {
        "name": "checkin_file",
        "description": "Release a file checkout lock.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "File path relative to project root"}
            },
            "required": ["file"]
        }
    },
    {
        "name": "get_context",
        "description": "Pull project context: team roster, file checkouts, recent messages. Use when coordinating with teammates.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    # --- Pegify Context MCP (Phase 1) — shared project context for agents ---
    {
        "name": "get_project_identity",
        "description": "Get stable project identity (name, goal, stack, conventions, roster). Call this FIRST to orient yourself in a new session. Cached for 1 hour — cheap to call.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_architecture_snapshot",
        "description": "Get current branch, HEAD sha, languages, and directory tree summary. Stable per git commit — cheap to call. Use this for orientation before reading individual files.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_recent_activity",
        "description": "Get recent observations (decisions, bugfixes, features, discoveries, blockers) from all agents on this project. Newest first. Call this LAST after stable context tools — it is volatile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max observations to return", "default": 20}
            }
        }
    },
    {
        "name": "record_observation",
        "description": "Record a decision, bugfix, feature, discovery, or blocker. Provide evidence (commit_sha, file_refs) — observations without evidence that reference real artifacts may be rejected by the reconciler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["decision", "bugfix", "feature", "discovery", "blocker"]},
                "body": {"type": "string", "description": "What happened"},
                "evidence": {"type": "object", "description": "Provenance refs (commit_sha, file_refs, test_ids)"}
            },
            "required": ["type", "body"]
        }
    },
]


def handle_initialize(req_id):
    write_response({
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
            "experimental": {
                "claude/channel": {},
            },
        },
        "serverInfo": {"name": "pegify-channel", "version": "0.3.0"},
    }, req_id)


def handle_tools_list(req_id):
    write_response({"tools": TOOLS}, req_id)


def handle_tool_call(req_id, params: dict):
    name = params.get("name", "")
    args = params.get("arguments", {})
    identity = resolve_identity()
    agent = identity.get("agent", "claude")

    if name == "reply":
        channel = args.get("channel", identity.get("channel", "my-team"))
        body = args.get("body", "")
        # Tag active-session replies so users can see which adapter path handled the message
        # (idle responder tags [sdk]/[cli]; MCP reply = active terminal session)
        tagged_body = f"{body}\n\n`[active]`"
        result = daemon_post(f"/channels/{channel}/say", {
            "sender": agent,
            "body": tagged_body,
            "type": "info",
        })
        if result:
            text = f"Sent to {channel}"
        else:
            text = "Failed to send — daemon may be offline"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "read_channel":
        channel = args.get("channel", identity.get("channel", "my-team"))
        limit = args.get("limit", 20)
        result = daemon_get(f"/channels/{channel}/log?limit={limit}")
        if result:
            messages = result.get("messages", [])
            lines = []
            for msg in messages[-limit:]:
                sender = msg.get("from", msg.get("sender", "?"))
                body = msg.get("body", "")
                lines.append(f"[{sender}] {body}")
            text = "\n".join(lines) if lines else "(no messages)"
        else:
            text = "Failed to read — daemon may be offline"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "list_agents":
        result = daemon_get("/agents")
        if result:
            agents = result.get("agents", [])
            lines = [f"{a.get('name', '?')} ({a.get('state', '?')})" for a in agents]
            text = "\n".join(lines) if lines else "(no agents)"
        else:
            text = "Failed — daemon may be offline"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "list_channels":
        result = daemon_get("/channels")
        if result:
            channels = result.get("channels", [])
            text = "\n".join(channels) if channels else "(no channels)"
        else:
            text = "Failed — daemon may be offline"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "check_messages":
        result = daemon_get(f"/agents/{agent}/messages?limit=20")
        if result:
            messages = result.get("messages", [])
            if not messages:
                text = "No pending messages."
            else:
                lines = []
                for msg in messages:
                    sender = msg.get("from_agent", "?")
                    body = msg.get("body", "")
                    channel = msg.get("channel", "")
                    lines.append(f"[#{channel}] {sender}: {body}")
                    msg_id = msg.get("id")
                    if msg_id:
                        daemon_post(f"/messages/{msg_id}/read", {})
                text = "\n".join(lines)
        else:
            text = "Failed — daemon may be offline"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "checkout_file":
        file_path = args.get("file", "")
        result = auto_checkout(file_path)
        if result and result.get("conflict"):
            text = f"⚠ {file_path} checked out by {result['held_by']}. Coordinate before editing."
        else:
            text = f"Checked out {file_path}"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "checkin_file":
        file_path = args.get("file", "")
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        daemon_post("/files/checkin", {"file": file_path, "project": project})
        write_response({"content": [{"type": "text", "text": f"Released {file_path}"}]}, req_id)

    elif name == "get_context":
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if project:
            import base64
            project_b64 = base64.urlsafe_b64encode(project.encode()).decode()
            ctx = daemon_get(f"/context/{project_b64}")
            if ctx:
                lines = []
                team = ctx.get("team")
                if team:
                    lines.append(f"Lead: {team['lead']['name']}")
                    for m in team.get("members", []):
                        lines.append(f"  Teammate: {m['name']}" + (f" ({m['role']})" if m['role'] else ""))
                checkouts = ctx.get("checkouts", [])
                if checkouts:
                    lines.append("Files checked out:")
                    for co in checkouts:
                        lines.append(f"  {co['file']} — {co['agent']} ({co['since']})")
                msgs = ctx.get("recent_messages", [])
                if msgs:
                    lines.append("Recent messages:")
                    for msg in msgs:
                        lines.append(f"  {msg['from']}: {msg['text'][:100]}")
                text = "\n".join(lines) if lines else "No team context available."
            else:
                text = "Could not fetch project context."
        else:
            text = "No project directory set."
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    # --- Pegify Context MCP (Phase 1) — shared project context ---
    elif name == "get_project_identity":
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if not project:
            write_response({"content": [{"type": "text", "text": "No project directory set."}]}, req_id)
            return
        result = daemon_post_raw("/context/identity", {"project_path": project})
        text = result if result else "Failed to fetch project identity."
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "get_architecture_snapshot":
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if not project:
            write_response({"content": [{"type": "text", "text": "No project directory set."}]}, req_id)
            return
        result = daemon_post_raw("/context/architecture", {"project_path": project})
        text = result if result else "Failed to fetch architecture snapshot."
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "get_recent_activity":
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if not project:
            write_response({"content": [{"type": "text", "text": "No project directory set."}]}, req_id)
            return
        limit = args.get("limit", 20)
        result = daemon_post_raw("/context/recent-activity", {"project_path": project, "limit": limit})
        text = result if result else "[]"
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    elif name == "record_observation":
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if not project:
            write_response({"content": [{"type": "text", "text": "No project directory set."}]}, req_id)
            return
        body = {
            "project_path": project,
            "agent_id": agent,
            "type": args.get("type", ""),
            "body": args.get("body", ""),
            "evidence": args.get("evidence"),
        }
        result = daemon_post("/context/observations", body)
        if result:
            text = f"Observation recorded (id={result.get('id', '?')})"
        else:
            text = "Failed to record observation."
        write_response({"content": [{"type": "text", "text": text}]}, req_id)

    else:
        write_error(-32601, f"Unknown tool: {name}", req_id)


# --- Message Poller (background thread) ---

def message_poller(agent: str, subscriptions: dict):
    """Background thread that polls daemon for new messages across all channels."""
    from collections import OrderedDict
    # Use an OrderedDict as a bounded seen-set: keys are msg IDs, insertion order preserved.
    # This avoids the replay vulnerability from arbitrary set truncation.
    _SEEN_MAX = 1000
    seen_ids: OrderedDict = OrderedDict()
    log = lambda msg: sys.stderr.write(f"[pegify-mcp] {msg}\n")
    error_backoff = 0  # consecutive error count for exponential backoff

    channels = list(subscriptions.keys())
    log(f"Poller started for {agent} on {', '.join(channels)}")

    while True:
        try:
            time.sleep(POLL_INTERVAL)

            # Heartbeat — keeps live session registered but does NOT reset
            # the stale timer (source=poller). Real tool-call hooks send source=hook.
            hb = daemon_post("/live-sessions/heartbeat", {"agent": agent, "source": "poller"})
            if hb is None:
                # Daemon unreachable — backoff
                error_backoff = min(error_backoff + 1, 5)
                backoff_secs = 2 ** error_backoff
                log(f"Daemon unreachable, backing off {backoff_secs}s")
                time.sleep(backoff_secs)
                continue

            # Daemon is reachable — reset backoff
            error_backoff = 0

            if hb.get("unknown"):
                # Daemon restarted — re-register live session
                log(f"Re-registering live session after daemon restart")
                _fresh_identity = resolve_identity()
                session_id = os.environ.get("CLAUDE_SESSION_ID", "") or _fresh_identity.get("session_id", f"mcp-{agent}")
                project = os.environ.get("CLAUDE_PROJECT_DIR", "")
                channel = list(subscriptions.keys())[0] if subscriptions else ""
                _identity = resolve_identity()
                _company_id = _identity.get("company", "")
                _rereg_body = {
                    "session_id": session_id,
                    "agent": agent,
                    "channel": channel,
                    "project": project,
                    "adapter": "claude-code",
                }
                if _company_id:
                    _rereg_body["company_id"] = _company_id
                daemon_post("/live-sessions/register", _rereg_body)

            # Poll agent's message store for pending messages
            result = daemon_get(f"/agents/{agent}/messages?limit=10")
            if not isinstance(result, dict):
                continue

            for msg in result.get("messages", []):
                msg_id = msg.get("id")
                if not msg_id or msg_id in seen_ids:
                    continue

                # Add to bounded seen set (evict oldest if full)
                seen_ids[msg_id] = True
                if len(seen_ids) > _SEEN_MAX:
                    seen_ids.popitem(last=False)

                sender = msg.get("from_agent", msg.get("from", "?"))
                body = msg.get("body", "")
                channel = msg.get("channel", "")

                if sender == agent:
                    continue

                is_mention = f"@{agent}" in body or "@all" in body
                priority = "mention" if is_mention else "channel"

                mode = subscriptions.get(channel, "listen")
                if mode == "listen" and not is_mention:
                    continue

                log(f"Queued [{priority}] from {sender} on #{channel}: {body[:50]}...")

                _message_queue.push({
                    "from": sender,
                    "body": body,
                    "channel": channel,
                    "priority": priority,
                    "timestamp": msg.get("created_at", ""),
                    "message_id": msg_id,
                })

                daemon_post(f"/messages/{msg_id}/read", {})

            if _message_queue.count() > 0:
                msgs = _message_queue.drain()
                push_batch_notification(agent, msgs)

        except Exception as e:
            error_backoff = min(error_backoff + 1, 5)
            backoff_secs = 2 ** error_backoff
            log(f"Poller error: {e} (backing off {backoff_secs}s)")
            time.sleep(backoff_secs)


def push_batch_notification(agent: str, msgs: list):
    """Push a batch of messages as a single channel notification."""
    by_channel: dict = {}
    for m in msgs:
        ch = m.get("channel", "?")
        by_channel.setdefault(ch, []).append(m)

    lines = [f"[pegify] {len(msgs)} new message{'s' if len(msgs) != 1 else ''} across {len(by_channel)} channel{'s' if len(by_channel) != 1 else ''}:\n"]

    for ch, ch_msgs in by_channel.items():
        lines.append(f"#{ch}:")
        for m in ch_msgs:
            lines.append(f"  [{m['from']}] {m['body']}")
        lines.append("")

    lines.append("Reply to active channels using the pegify reply MCP tool.")

    content = "\n".join(lines)

    write_notification("notifications/claude/channel", {
        "content": content,
        "meta": {
            "source": "pegify",
            "count": len(msgs),
            "channels": list(by_channel.keys()),
        },
    })


# --- Main Loop ---

def main():
    identity = resolve_identity()
    agent = identity.get("agent", "claude")
    subscriptions = resolve_subscriptions(identity)

    sys.stderr.write(f"[pegify-mcp] Starting channel server for {agent} on {list(subscriptions.keys())}\n")

    # Register live session (recovers after daemon restart)
    channel = identity.get("channel", "")
    company_id = identity.get("company", "")
    project = os.environ.get("CLAUDE_PROJECT_DIR", "")
    # Session ID: from env, from identity (session file written by session-start hook), or fallback
    session_id = os.environ.get("CLAUDE_SESSION_ID", "") or identity.get("session_id", "")
    if session_id:
        sys.stderr.write(f"[pegify-mcp] Using session_id={session_id}\n")
    if channel and agent:
        reg_body = {
            "session_id": session_id or "mcp-" + agent,
            "agent": agent,
            "channel": channel,
            "project": project,
            "adapter": "claude-code",
        }
        if company_id:
            reg_body["company_id"] = company_id
        daemon_post("/live-sessions/register", reg_body)

    # Start background message poller
    poller = threading.Thread(target=message_poller, args=(agent, subscriptions), daemon=True)
    poller.start()

    # Main thread: read stdin, handle MCP requests
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            handle_initialize(req_id)
        elif method == "notifications/initialized":
            pass  # Client acknowledgment — ignore
        elif method == "tools/list":
            handle_tools_list(req_id)
        elif method == "tools/call":
            handle_tool_call(req_id, params)
        elif method == "ping":
            write_response({}, req_id)
        else:
            if req_id is not None:
                write_error(-32601, f"Method not found: {method}", req_id)


if __name__ == "__main__":
    main()
