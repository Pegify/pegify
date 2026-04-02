#!/usr/bin/env python3
"""PreToolUse hook — route ALL permission decisions through Pegify.

When approvals are enabled, this hook takes over Claude Code's permission system:
- Safe/read-only tools: instant allow (no prompt)
- Unsafe tools: sent to Pegify daemon for remote approval (TUI, Telegram, CLI)
- Claude Code never shows its own permission prompt
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)


def resolve_config() -> dict | None:
    """Resolve approval config from .pegify.yaml or defaults."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        config_path = Path(project_dir) / ".pegify.yaml"
        if config_path.exists():
            return yaml.safe_load(config_path.read_text())
    return None


def daemon_url(path: str) -> str:
    return f"http://127.0.0.1:7654{path}"


def daemon_post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        daemon_url(path), data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def daemon_get(path: str) -> dict:
    req = urllib.request.Request(daemon_url(path))
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def output_decision(decision: str, reason: str = "", context: str = ""):
    """Output a structured hook response."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
        }
    }
    if reason:
        result["hookSpecificOutput"]["permissionDecisionReason"] = reason
    if context:
        result["hookSpecificOutput"]["additionalContext"] = context
    print(json.dumps(result))


def is_safe_tool(tool_name: str, tool_input: dict) -> bool:
    """Check if a tool is safe and can be auto-approved."""
    safe_tools = {"Read", "Glob", "Grep", "Skill", "Agent", "TaskCreate",
                  "TaskUpdate", "TaskList", "TaskGet", "ToolSearch", "WebSearch",
                  "WebFetch", "SendMessage"}
    if tool_name in safe_tools:
        return True
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if cmd.startswith(("pegify ", ".venv/bin/pegify ", "curl -s http://localhost:7654",
                          "curl -s http://127.0.0.1:7654")):
            return True
    return False


def read_inbox(agent: str) -> str:
    """Read inbox from file-based inbox AND SQLite MessageStore. Returns '' if empty."""
    lines = []

    # 1. File-based inbox (legacy — approvals still use this)
    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
    inbox_dir = Path(home) / "inbox" / agent
    if inbox_dir.exists():
        for path in sorted(inbox_dir.glob("*.json")):
            try:
                item = json.loads(path.read_text())
                path.unlink()
                if item.get("type") == "message":
                    p = item.get("payload", {})
                    lines.append(f"  {p.get('from', '?')}: {p.get('body', '')}")
                elif item.get("type") == "approval_decision":
                    p = item.get("payload", {})
                    lines.append(f"  {p.get('decided_by', '?')} {p.get('decision', '?')} {p.get('tool', '?')}: {p.get('tool_input_summary', '')}")
            except (json.JSONDecodeError, OSError):
                continue

    # 2. SQLite MessageStore (new — @mentions and direct messages)
    try:
        req = urllib.request.Request(daemon_url(f"/agents/{agent}/messages?limit=5"))
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            for msg in data.get("messages", []):
                lines.append(f"  {msg.get('from_agent', '?')}: {msg.get('body', '')}")
                # Mark as read so it doesn't repeat
                msg_id = msg.get("id")
                if msg_id:
                    try:
                        mark_req = urllib.request.Request(
                            daemon_url(f"/messages/{msg_id}/read"),
                            method="POST",
                        )
                        urllib.request.urlopen(mark_req, timeout=1)
                    except Exception:
                        pass
    except Exception:
        pass  # Daemon may not be running

    if not lines:
        return ""
    return "[pegify] New messages:\n" + "\n".join(lines[:10])


def main():
    # Read hook event from stdin
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    session_id = event.get("session_id", "")

    # Load config
    config = resolve_config()
    if not config:
        sys.exit(0)  # No config = let Claude Code handle it normally

    approvals = config.get("approvals", {})
    if not approvals.get("enabled", False):
        sys.exit(0)  # Disabled = let Claude Code handle it normally

    # Read inbox for real-time messages — check both configured identity and all DB agents
    agent = config.get("agent", "unknown")

    # Resolve session display name (e.g. "Nebula") from session identity file
    session_agent = agent
    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
    session_dir = Path(home) / "sessions"
    if session_dir.is_dir():
        for f in session_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(f.read_text())
                if data and data.get("display_name"):
                    session_agent = data["display_name"]
                    break
            except Exception:
                continue

    # Heartbeat to daemon — marks live session active, re-registers if needed
    try:
        hb_body = json.dumps({"agent": session_agent}).encode()
        hb_req = urllib.request.Request(
            daemon_url("/live-sessions/heartbeat"),
            data=hb_body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(hb_req, timeout=1) as resp:
            hb_data = json.loads(resp.read().decode())
            # If heartbeat says unknown agent, re-register
            if hb_data.get("unknown"):
                project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
                reg_body = json.dumps({
                    "agent": session_agent,
                    "session_id": session_id,
                    "channel": config.get("channel", ""),
                    "project": project_dir,
                    "adapter": "claude-code",
                }).encode()
                reg_req = urllib.request.Request(
                    daemon_url("/live-sessions/register"),
                    data=reg_body,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(reg_req, timeout=2)
                # Also ensure agent is active in store
                state_body = json.dumps({"state": "active"}).encode()
                state_req = urllib.request.Request(
                    daemon_url(f"/agents/{session_agent}"),
                    data=state_body, method="PATCH",
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(state_req, timeout=1)
    except Exception:
        pass

    inbox_context = read_inbox(session_agent)
    # Also check inbox for other agent identities on this channel
    channel = config.get("channel", "")
    if channel:
        try:
            req = urllib.request.Request(daemon_url(f"/agents?state=dormant"))
            with urllib.request.urlopen(req, timeout=2) as resp:
                agents_data = json.loads(resp.read().decode())
                for a in agents_data.get("agents", []):
                    if a.get("channel") == channel and a.get("name") != agent:
                        extra = read_inbox(a["name"])
                        if extra:
                            inbox_context = (inbox_context + "\n" + extra).strip() if inbox_context else extra
        except Exception:
            pass

    # Safe tools: instant allow, no prompt at all
    if is_safe_tool(tool_name, tool_input):
        output_decision("allow", "Safe tool (auto-approved by Pegify)", context=inbox_context)
        return

    channel = approvals.get("channel", config.get("channel", "default"))
    timeout = approvals.get("timeout", 600)
    timeout_action = approvals.get("timeout_action", "ask")

    # timeout 0 with allow = instant auto-approve all tools
    if timeout <= 0 and timeout_action == "allow":
        output_decision("allow", "Auto-approved (timeout=0)", context=inbox_context)
        return

    # Get project name from CLAUDE_PROJECT_DIR
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    project = Path(project_dir).name if project_dir else ""

    # Create approval request on daemon
    try:
        result = daemon_post("/approvals/request", {
            "tool": tool_name,
            "input": tool_input,
            "session_id": session_id,
            "agent": agent,
            "channel": channel,
            "project": project,
        })
    except Exception:
        # Daemon unreachable — fall back to timeout action
        if timeout_action == "allow":
            output_decision("allow", "Daemon unreachable (auto-allow)", context=inbox_context)
        elif timeout_action == "deny":
            output_decision("deny", "Daemon unreachable (auto-deny)", context=inbox_context)
        return

    request_id = result.get("request_id", "")
    if not request_id:
        output_decision("allow", "No request ID returned", context=inbox_context)
        return

    # Wait for approval decision via inbox files
    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
    inbox_dir = Path(home) / "inbox" / agent
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Check inbox for approval decision matching our request
        if inbox_dir.exists():
            for path in sorted(inbox_dir.glob("*.json")):
                try:
                    item = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    continue
                if (item.get("type") == "approval_decision" and
                        item.get("payload", {}).get("request_id") == request_id):
                    path.unlink()
                    decision = item["payload"]["decision"]
                    decided_by = item["payload"].get("decided_by", "user")
                    if decision == "approved":
                        output_decision("allow", f"Approved via Pegify by {decided_by}", context=inbox_context)
                    else:
                        output_decision("deny", f"Denied via Pegify by {decided_by}", context=inbox_context)
                    return

        # Fallback: also check HTTP in case inbox file wasn't written
        try:
            status = daemon_get(f"/approvals/{request_id}")
            if status.get("status") == "approved":
                decided_by = status.get("decided_by", "user")
                output_decision("allow", f"Approved via Pegify by {decided_by}", context=inbox_context)
                return
            elif status.get("status") == "denied":
                decided_by = status.get("decided_by", "user")
                output_decision("deny", f"Denied via Pegify by {decided_by}", context=inbox_context)
                return
        except Exception:
            pass

        time.sleep(1)

    # Timeout — return configured action
    if timeout_action == "deny":
        output_decision("deny", "Approval timed out (no response)", context=inbox_context)
    elif timeout_action == "allow":
        output_decision("allow", "Approval timed out (auto-allow)", context=inbox_context)
    else:
        output_decision("allow", "Approval timed out (default allow)", context=inbox_context)


if __name__ == "__main__":
    main()
