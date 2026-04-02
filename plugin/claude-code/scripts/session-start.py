#!/usr/bin/env python3
"""SessionStart hook — check unread Pegify messages and inject context."""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)  # PyYAML not available, skip silently


def resolve_identity() -> dict | None:
    """Resolve Pegify identity from project config or global default."""
    # 1. Per-project .pegify.yaml
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        project_config = Path(project_dir) / ".pegify.yaml"
        if project_config.exists():
            data = yaml.safe_load(project_config.read_text())
            if data and "agent" in data and "channel" in data:
                return data

    # 2. Global default
    pegify_home = Path(os.environ.get("PEGIFY_HOME", Path.home() / ".pegify"))
    default_id = pegify_home / ".default-identity"
    if default_id.exists():
        return yaml.safe_load(default_id.read_text())

    return None


def main():
    # Check if pegify is installed
    if not shutil.which("pegify"):
        return

    # Read hook event from stdin (all hooks receive session_id)
    session_id = ""
    try:
        event = json.loads(sys.stdin.read())
        session_id = event.get("session_id", "")
    except (json.JSONDecodeError, EOFError):
        pass

    identity = resolve_identity()
    if not identity:
        print("[pegify] No identity configured. Run /pegify:setup to get started.")
        return

    agent = identity.get("agent", "unknown")
    channel = identity.get("channel", "default")

    # Detect runtime context
    entrypoint = os.environ.get("CLAUDE_CODE_ENTRYPOINT", "cli")
    if entrypoint == "ide" or os.environ.get("VSCODE_PID"):
        runtime_context = "VS Code"
    else:
        runtime_context = "CLI"

    # Auto-register with pool and write session identity
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    assigned_name = agent  # fallback
    assigned_id = ""

    # Headless sessions: daemon already registered the agent — skip auto-register
    headless_name = os.environ.get("PEGIFY_DISPLAY_NAME")
    if headless_name:
        assigned_name = headless_name
    elif session_id:
        try:
            reg_body = json.dumps({
                "channel": channel,
                "runtime": "claude-code",
                "runtime_context": runtime_context,
                "project": project_dir,
                "created_by": "session-start",
            }).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:7654/agents/auto-register",
                data=reg_body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                reg_data = json.loads(resp.read().decode())
                assigned_name = reg_data.get("name", agent)
                assigned_id = reg_data.get("agent_id", "")
        except Exception:
            pass

        # Write session identity file
        session_dir = Path(os.environ.get("PEGIFY_HOME", Path.home() / ".pegify")) / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / f"{session_id}.yaml"
        session_file.write_text(yaml.dump({
            "agent_id": assigned_id,
            "display_name": assigned_name,
            "channel": channel,
            "session_id": session_id,
        }))

        # Register live session
        try:
            ls_body = json.dumps({
                "session_id": session_id,
                "agent": assigned_name,
                "channel": channel,
                "project": project_dir,
                "adapter": "claude-code",
            }).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:7654/live-sessions/register",
                data=ls_body,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    print(f"[pegify] {assigned_name} on {channel}" + (f" ({assigned_id})" if assigned_id else ""))

    # Register agent inbox for real-time message delivery
    try:
        body = json.dumps({"channels": [channel]}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:7654/inbox/{assigned_name}/register",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass  # Daemon may not be running — not an error

    # Fetch unread messages
    try:
        result = subprocess.run(
            ["pegify", "unread", channel, "--summary"],
            capture_output=True, text=True, timeout=10,
        )
        output = result.stdout.strip()
        if output:
            print(f"[pegify] Unread messages:")
            for line in output.split("\n")[:10]:
                print(f"  {line}")
        else:
            print("[pegify] No unread messages.")
    except Exception:
        print("[pegify] Could not check unread messages.")

    print()
    print(f'[pegify] To contact the user, run: pegify say {channel} "your message"')
    print("[pegify] Cross-session memory: use `pegify memory` commands for shared context.")
    print("The user may be away from this terminal. Use Pegify for all communication.")


if __name__ == "__main__":
    main()
