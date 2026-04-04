#!/usr/bin/env python3
"""Stop hook — forward agent's last response to Pegify channel (→ Telegram).

Reads the conversation transcript, extracts the last assistant text,
and sends it via pegify say. This ensures all agent output reaches
the user on Telegram regardless of agent type.
"""

import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(0)


def resolve_config() -> dict | None:
    """Resolve Pegify config from .pegify.yaml."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        config_path = Path(project_dir) / ".pegify.yaml"
        if config_path.exists():
            return yaml.safe_load(config_path.read_text())
    return None


def extract_last_assistant_text(transcript_path: str) -> str:
    """Read the JSONL transcript and extract the last assistant text blocks."""
    path = Path(transcript_path)
    if not path.exists():
        return ""

    # Read last 50 lines (enough to find the final assistant message)
    lines = path.read_text().strip().split("\n")
    lines = lines[-50:]

    last_texts = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Look for assistant messages with text content
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue

        content = msg.get("content", [])
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    last_texts.append(text)

        # Found the last assistant message — stop looking
        if last_texts:
            break

    if not last_texts:
        return ""

    # Join all text blocks from the last assistant message
    return "\n".join(reversed(last_texts))


def pegify_say(channel: str, agent: str, message: str):
    """Send a message via the Pegify daemon HTTP API."""
    try:
        body = json.dumps({
            "sender": agent,
            "body": message,
            "type": "info",
        }).encode()
        req = _make_req(
            f"http://127.0.0.1:7654/channels/{channel}/say",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass  # Daemon may not be running


# Need urllib for pegify_say
import urllib.request


def _api_token() -> str:
    token_file = Path.home() / ".pegify" / "api-token"
    if token_file.exists():
        return token_file.read_text().strip()
    return ""


def _make_req(url: str, data: bytes | None = None, headers: dict | None = None) -> urllib.request.Request:
    hdrs = dict(headers or {})
    token = _api_token()
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, data=data, headers=hdrs)


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Don't recurse if this stop was triggered by a stop hook
    if event.get("stop_hook_active"):
        sys.exit(0)

    config = resolve_config()
    if not config:
        sys.exit(0)

    agent = config.get("agent", "")
    channel = config.get("channel", "")
    if not agent or not channel:
        sys.exit(0)

    session_id = event.get("session_id", "")
    transcript_path = event.get("transcript_path", "")

    # Capture session context in Pegify MemoryStore
    if transcript_path and agent:
        try:
            cap_body = json.dumps({
                "agent": agent,
                "transcript_path": transcript_path,
            }).encode()
            cap_req = _make_req(
                "http://127.0.0.1:7654/live-sessions/capture-context",
                data=cap_body,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(cap_req, timeout=5)
        except Exception:
            pass

    # Resolve session display name (e.g. "Nebula") from this session's identity file
    session_agent = agent
    session_file = None
    try:
        session_dir = Path.home() / ".pegify" / "sessions"
        if session_id:
            # Look for this specific session's file ONLY — never touch other sessions' files
            session_file = session_dir / f"{session_id}.yaml"
            if session_file.exists():
                data = yaml.safe_load(session_file.read_text())
                if data and data.get("display_name"):
                    session_agent = data["display_name"]
            else:
                session_file = None  # Not our file — don't clean up anything
        # Check PEGIFY_DISPLAY_NAME env var (set by headless spawner)
        if session_agent == agent:
            env_name = os.environ.get("PEGIFY_DISPLAY_NAME")
            if env_name:
                session_agent = env_name
    except Exception:
        pass

    # Unregister live session — include session_id so the daemon can guard
    # against stale hooks unregistering a newer session's registration
    if session_agent:
        try:
            unreg_body = json.dumps({"session_id": session_id}).encode() if session_id else None
            unreg_req = _make_req(
                f"http://127.0.0.1:7654/live-sessions/{session_agent}/unregister",
                data=unreg_body,
                headers={"Content-Type": "application/json"} if unreg_body else None,
            )
            unreg_req.method = "POST"
            urllib.request.urlopen(unreg_req, timeout=2)
        except Exception:
            pass

    # Clean up only this session's identity file
    if session_file and session_file.exists():
        try:
            session_file.unlink()
        except Exception:
            pass

    # Mark agent as dormant in the agent store
    if session_agent:
        try:
            body = json.dumps({"state": "dormant"}).encode()
            req = _make_req(
                f"http://127.0.0.1:7654/agents/{session_agent}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            req.method = "PATCH"
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    # Skip final message forwarding for headless sessions — _stream_output
    # already forwarded all text blocks to the channel during the session.
    # Detect headless: --print flag or --output-format in parent command.
    is_headless = os.environ.get("PEGIFY_HEADLESS") == "1"
    if not is_headless:
        # Also detect by checking if this session was spawned as headless
        try:
            req = _make_req(f"http://127.0.0.1:7654/sessions")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                for s in data.get("sessions", []):
                    if s.get("display_name") == session_agent or s.get("session_id") == session_id:
                        is_headless = True
                        break
        except Exception:
            pass

    if is_headless:
        sys.exit(0)

    if not transcript_path:
        sys.exit(0)

    text = extract_last_assistant_text(transcript_path)
    if not text:
        sys.exit(0)

    # Truncate very long responses for Telegram readability
    if len(text) > 2000:
        text = text[:1997] + "..."

    pegify_say(channel, session_agent, text)


if __name__ == "__main__":
    main()
