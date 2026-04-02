#!/usr/bin/env python3
"""UserPromptSubmit hook — heartbeat to daemon + inject pending messages.

Fires every time the user types a prompt. Two jobs:
1. Send heartbeat to daemon (marks session active, kills fork if running)
2. Inject pending messages + fork summary as additionalContext
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)


def resolve_config() -> dict | None:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        config_path = Path(project_dir) / ".pegify.yaml"
        if config_path.exists():
            return yaml.safe_load(config_path.read_text())
    return None


def daemon_url(path: str) -> str:
    return f"http://127.0.0.1:7654{path}"


def read_inbox(agent: str) -> str:
    """Read pending messages from SQLite MessageStore."""
    lines = []
    try:
        req = urllib.request.Request(daemon_url(f"/agents/{agent}/messages?limit=5"))
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            for msg in data.get("messages", []):
                lines.append(f"  {msg.get('from_agent', '?')}: {msg.get('body', '')}")
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
        pass
    if not lines:
        return ""
    return "[pegify] New messages:\n" + "\n".join(lines[:10])


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    config = resolve_config()
    if not config:
        sys.exit(0)

    agent = config.get("agent", "unknown")

    # 1. Heartbeat — marks active, returns fork status
    fork_info = {}
    try:
        body = json.dumps({"agent": agent}).encode()
        req = urllib.request.Request(
            daemon_url("/live-sessions/heartbeat"),
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            fork_info = json.loads(resp.read().decode())
    except Exception:
        pass

    # 2. Read pending messages
    inbox_context = read_inbox(agent)

    # 3. Add fork summary if fork was killed or completed
    fork_summary = fork_info.get("fork_summary", "")
    if fork_info.get("fork_killed"):
        inbox_context = (
            (inbox_context + "\n" if inbox_context else "")
            + "[pegify] A forked session was handling messages while you were idle. "
            + "It was stopped because you're back. Check pending messages above.\n"
            + f"For context from the fork: pegify memory recall '' --agent {agent}"
        )
    elif fork_summary:
        inbox_context = (
            (inbox_context + "\n" if inbox_context else "")
            + f"[pegify] While you were idle, a forked session handled messages:\n"
            + f"  {fork_summary}\n"
            + f"For full details: pegify memory recall '' --agent {agent}\n"
            + f"For message history: pegify msg history {agent} --limit 20"
        )

    if not inbox_context:
        sys.exit(0)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": inbox_context,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
