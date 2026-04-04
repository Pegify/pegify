#!/usr/bin/env python3
"""PostToolUse hook — signal pending messages at natural breakpoints.

Fires after each tool call. Checks daemon for pending message count.
If messages are waiting, adds additionalContext prompting the agent
to check and respond. Lightweight — just one HTTP GET.
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


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Resolve agent identity from .pegify.yaml
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        sys.exit(0)
    config_path = Path(project_dir) / ".pegify.yaml"
    if not config_path.exists():
        sys.exit(0)
    config = yaml.safe_load(config_path.read_text())
    if not config:
        sys.exit(0)

    agent = config.get("agent", "")
    if not agent:
        sys.exit(0)

    # Resolve session display name (may differ from config agent)
    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
    session_dir = Path(home) / "sessions"
    if session_dir.is_dir():
        for f in session_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(f.read_text())
                if data and data.get("display_name"):
                    agent = data["display_name"]
                    break
            except Exception:
                continue

    # Fetch pending messages with content — marks them as read
    token_file = Path.home() / ".pegify" / "api-token"
    token = token_file.read_text().strip() if token_file.exists() else ""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:7654/agents/{agent}/messages?limit=5")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=1) as resp:
            data = json.loads(resp.read().decode())
            messages = data.get("messages", [])
    except Exception:
        sys.exit(0)  # Daemon offline — skip silently

    # Filter out own messages and already-read ones
    pending = [m for m in messages if m.get("from_agent", m.get("from", "")) != agent and not m.get("read")]
    if not pending:
        sys.exit(0)

    channel = config.get("channel", "my-team")
    lines = []
    for m in pending:
        sender = m.get("from_agent", m.get("from", "?"))
        body = m.get("body", "")
        msg_id = m.get("id")
        lines.append(f"  [{sender}] {body}")
        # Mark as read
        if msg_id:
            try:
                mark_req = urllib.request.Request(
                    f"http://127.0.0.1:7654/messages/{msg_id}/read",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                if token:
                    mark_req.add_header("Authorization", f"Bearer {token}")
                urllib.request.urlopen(mark_req, timeout=1)
            except Exception:
                pass
    context = (
        f"[pegify] {len(pending)} message{'s' if len(pending) != 1 else ''} on #{channel}:\n"
        + "\n".join(lines)
        + "\nUse the pegify reply MCP tool to respond."
    )

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
