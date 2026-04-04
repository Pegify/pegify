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


def _api_token() -> str:
    token_file = Path.home() / ".pegify" / "api-token"
    if token_file.exists():
        return token_file.read_text().strip()
    return ""


def daemon_post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    token = _api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(daemon_url(path), data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def daemon_get(path: str) -> dict:
    req = urllib.request.Request(daemon_url(path))
    token = _api_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
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


def load_approval_config() -> dict:
    """Load approval config from daemon or fallback defaults."""
    defaults = {
        "mode": "smart",
        "auto_approve_tools": [
            "Read", "Glob", "Grep", "Skill", "Agent", "TaskCreate",
            "TaskUpdate", "TaskList", "TaskGet", "ToolSearch", "WebSearch",
            "WebFetch", "SendMessage",
        ],
        "always_ask_tools": [
            "Bash(rm ", "Bash(sudo ", "Bash(curl.*POST",
            "Bash(git push", "Bash(git reset --hard",
        ],
    }
    try:
        result = daemon_get("/config/approval")
        if result:
            return result
    except Exception:
        pass
    return defaults


def is_safe_tool(tool_name: str, tool_input: dict, approval_cfg: dict | None = None) -> bool:
    """Check if a tool is safe and can be auto-approved."""
    cfg = approval_cfg or load_approval_config()
    safe_tools = set(cfg.get("auto_approve_tools", []))

    if tool_name in safe_tools:
        return True
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Pegify and daemon commands are always safe
        if cmd.startswith(("pegify ", ".venv/bin/pegify ", "curl -s http://localhost:7654",
                          "curl -s http://127.0.0.1:7654")):
            return True
    return False


def is_dangerous_tool(tool_name: str, tool_input: dict, approval_cfg: dict | None = None) -> bool:
    """Check if a tool matches the always-ask patterns (dangerous)."""
    import re
    cfg = approval_cfg or load_approval_config()
    patterns = cfg.get("always_ask_tools", [])

    tool_str = tool_name
    if tool_name == "Bash":
        tool_str = f"Bash({tool_input.get('command', '')})"

    for pattern in patterns:
        try:
            if re.search(pattern, tool_str):
                return True
        except re.error:
            # Pattern has unescaped special chars — fall back to substring match
            if pattern in tool_str:
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
    channel = ""
    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
        if project_dir:
            config_path = Path(project_dir) / ".pegify.yaml"
            if config_path.exists():
                cfg = yaml.safe_load(config_path.read_text())
                channel = cfg.get("channel", "my-team") if cfg else "my-team"
    except Exception:
        channel = "my-team"
    return (
        "[pegify] New messages:\n"
        + "\n".join(lines[:10])
        + f"\n[pegify] Reply via: pegify say {channel} \"your response\""
    )


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

    # Support both old format (approvals.enabled) and new format (approval.mode)
    approval_cfg = config.get("approval", {})
    approvals = config.get("approvals", {})
    if not approval_cfg.get("mode") and not approvals.get("enabled", False):
        sys.exit(0)  # No approval config = let Claude Code handle it normally

    # Read inbox for real-time messages — check both configured identity and all DB agents
    agent = config.get("agent", "unknown")

    # Resolve session display name from session identity file (skip _recent_ markers)
    session_agent = agent
    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
    session_dir = Path(home) / "sessions"
    session_id = event.get("session_id", "")
    if session_id and session_dir.is_dir():
        session_file = session_dir / f"{session_id}.yaml"
        if session_file.exists():
            try:
                data = yaml.safe_load(session_file.read_text())
                if data and data.get("display_name"):
                    session_agent = data["display_name"]
            except Exception:
                pass

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

    # Check for idle exchanges — inject as context when main session resumes
    # If session_id not in event, try env var or scan session files
    idle_exchange_context = ""
    exchange_session_id = session_id
    if not exchange_session_id:
        exchange_session_id = os.environ.get("CLAUDE_SESSION_ID", "")
    if not exchange_session_id:
        # Scan session files for this agent's session
        try:
            for f in Path(os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))).joinpath("sessions").glob("*_exchanges.log"):
                exchange_session_id = f.name.replace("_exchanges.log", "")
                break
        except Exception:
            pass
    try:
        home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
        exchange_log = Path(home) / "sessions" / f"{exchange_session_id}_exchanges.log"
        if exchange_log.exists():
            content = exchange_log.read_text().strip()
            if content:
                idle_exchange_context = (
                    "[pegify] While you were idle, you handled Telegram messages:\n"
                    + content
                    + "\nContinue from where you left off."
                )
                exchange_log.unlink()
    except Exception:
        pass

    if idle_exchange_context:
        inbox_context = (idle_exchange_context + "\n" + inbox_context).strip() if inbox_context else idle_exchange_context

    # Load approval mode config
    approval_cfg = load_approval_config()
    approval_mode = approval_cfg.get("mode", "smart")

    # MODE: auto — approve everything, no prompts ever
    if approval_mode == "auto":
        output_decision("allow", f"Auto-approved (mode=auto)", context=inbox_context)
        return

    # Safe tools: instant allow in both smart and strict modes
    if is_safe_tool(tool_name, tool_input, approval_cfg):
        output_decision("allow", "Safe tool (auto-approved by Pegify)", context=inbox_context)
        return

    # MODE: smart — auto-approve non-dangerous, ask for dangerous
    if approval_mode == "smart":
        if not is_dangerous_tool(tool_name, tool_input, approval_cfg):
            output_decision("allow", "Approved (mode=smart, non-dangerous)", context=inbox_context)
            return
        # Dangerous tool in smart mode — fall through to approval request

    # MODE: strict — everything non-safe goes to approval
    # (falls through naturally)

    channel = approvals.get("channel", config.get("channel", "default"))
    timeout = approvals.get("timeout", 600)
    timeout_action = approvals.get("timeout_action", "ask")

    # Legacy: timeout 0 with allow = instant auto-approve all tools
    if timeout <= 0 and timeout_action == "allow":
        output_decision("allow", "Auto-approved (timeout=0)", context=inbox_context)
        return

    # Get project name from CLAUDE_PROJECT_DIR
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    project = Path(project_dir).name if project_dir else ""

    # Create approval request on daemon (retry up to 2 times on failure)
    result = None
    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            result = daemon_post("/approvals/request", {
                "tool": tool_name,
                "input": tool_input,
                "session_id": session_id,
                "agent": agent,
                "channel": channel,
                "project": project,
            })
            break  # Success — exit retry loop
        except Exception:
            if attempt < max_retries:
                time.sleep(0.5 * attempt)  # Short backoff: 0.5s, 1.0s
                continue
            # All retries exhausted — daemon is unreachable
            # Only auto-allow if user explicitly configured timeout_action: allow
            if timeout_action == "allow":
                print(
                    "[pegify] WARNING: Daemon unreachable after retries. "
                    "Auto-allowing because timeout_action is explicitly set to 'allow'.",
                    file=sys.stderr,
                )
                output_decision("allow", "Daemon unreachable (explicit auto-allow configured)", context=inbox_context)
            else:
                print(
                    "[pegify] WARNING: Daemon unreachable after retries. "
                    "Denying tool use for safety. Start daemon with: pegify daemon start",
                    file=sys.stderr,
                )
                output_decision("deny", "Daemon unreachable — denied for safety", context=inbox_context)
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

    # Timeout — return configured action (default to deny for safety)
    if timeout_action == "allow":
        output_decision("allow", "Approval timed out (explicit auto-allow configured)", context=inbox_context)
    else:
        output_decision("deny", "Approval timed out (no response — denied for safety)", context=inbox_context)


if __name__ == "__main__":
    main()
