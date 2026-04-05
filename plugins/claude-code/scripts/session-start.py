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


def _api_token() -> str:
    token_file = Path.home() / ".pegify" / "api-token"
    if token_file.exists():
        return token_file.read_text().strip()
    return ""


def _auth_request(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 3) -> urllib.request.Request:
    """Create a request with API token auth."""
    hdrs = dict(headers or {})
    token = _api_token()
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=hdrs)
    return req


def resolve_identity() -> dict | None:
    """Resolve Pegify identity from project config or global default.

    Requires at least 'channel'. 'agent' is optional — will be resolved
    from project registry or assigned during claim-or-create.
    """
    # 1. Per-project .pegify.yaml
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if project_dir:
        project_config = Path(project_dir) / ".pegify.yaml"
        if project_config.exists():
            data = yaml.safe_load(project_config.read_text())
            if data and "channel" in data:
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
    company_id = identity.get("company", "")
    company_name = ""
    agent_info = {}  # populated by claim-or-create; may stay empty on reuse paths

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

    # Headless sessions: daemon already registered the agent — skip
    headless_name = os.environ.get("PEGIFY_DISPLAY_NAME")
    is_team_spawn = False
    lead_name = None

    if headless_name:
        assigned_name = headless_name
    elif session_id:
        # Check if this session already registered (hook may fire multiple times)
        session_dir = Path(os.environ.get("PEGIFY_HOME", Path.home() / ".pegify")) / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / f"{session_id}.yaml"

        if session_file.exists():
            # Reuse existing identity — don't create a duplicate agent
            try:
                existing = yaml.safe_load(session_file.read_text())
                if existing:
                    assigned_name = existing.get("display_name", agent)
                    assigned_id = existing.get("agent_id", "")
                    is_team_spawn = existing.get("team_spawn", False)
                    lead_name = existing.get("lead", None)
                    company_id = existing.get("company_id", company_id)
                    # Update channel/project from current config (may have changed)
                    stale = False
                    if existing.get("channel") != channel:
                        existing["channel"] = channel
                        stale = True
                    if project_dir and existing.get("project") != project_dir:
                        existing["project"] = project_dir
                        stale = True
                    if stale:
                        session_file.write_text(yaml.dump(existing))
            except Exception:
                pass
            # Fetch company name if we have an id but no name
            if company_id and not company_name:
                try:
                    req = _auth_request(f"http://127.0.0.1:7654/companies/{company_id}")
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        company_name = json.loads(resp.read().decode()).get("name", "")
                except Exception:
                    pass
        else:
            # Dedup concurrent hooks for the same project: if another hook
            # already registered within the last 5 seconds, reuse that result
            # instead of creating a duplicate agent.
            import time as _time
            agent_id_from_config = identity.get("agent_id", "")
            project_hash = project_dir.replace("/", "_") if project_dir else "default"
            recent_file = session_dir / f"_recent_{project_hash}.yaml"

            already_registered = False
            if recent_file.exists():
                try:
                    age = _time.time() - recent_file.stat().st_mtime
                    if age < 5:
                        recent_data = yaml.safe_load(recent_file.read_text())
                        if recent_data:
                            assigned_name = recent_data.get("display_name", agent)
                            assigned_id = recent_data.get("agent_id", "")
                            is_team_spawn = recent_data.get("team_spawn", False)
                            lead_name = recent_data.get("lead", None)
                            already_registered = True
                except Exception:
                    pass

            if not already_registered:
                # Check project agent registry — reclaim previous agent for this project
                if not agent_id_from_config and project_dir:
                    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
                    projects_dir = Path(home) / "projects"
                    projects_dir.mkdir(parents=True, exist_ok=True)
                    project_reg = projects_dir / f"{project_dir.replace('/', '_').strip('_')}.yaml"
                    if project_reg.exists():
                        try:
                            proj_data = yaml.safe_load(project_reg.read_text())
                            if proj_data:
                                # Find a reclaimable agent (not currently active in another session)
                                for prev in proj_data.get("agents", []):
                                    agent_id_from_config = prev.get("agent_id", "")
                                    agent = prev.get("name", agent)
                                    break  # Take the first (primary) agent
                        except Exception:
                            pass

                # Claim existing agent or create new one (with retry)
                reg_body = json.dumps({
                    "channel": channel,
                    "runtime": "claude-code",
                    "runtime_context": runtime_context,
                    "project": project_dir,
                    "agent_id": agent_id_from_config,
                    "created_by": "session-start",
                    "company_id": company_id,
                }).encode()
                registered = False
                for attempt in range(2):
                    try:
                        req = _auth_request(
                            "http://127.0.0.1:7654/agents/claim-or-create",
                            data=reg_body,
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=3) as resp:
                            reg_data = json.loads(resp.read().decode())
                            agent_info = reg_data.get("agent", {})
                            assigned_name = agent_info.get("name", agent)
                            assigned_id = agent_info.get("agent_id", "")
                            is_team_spawn = reg_data.get("team_spawn", False)
                            lead_name = reg_data.get("lead")

                            # Agent identity is stored in session file only
                            # (not .pegify.yaml — that's shared project config)
                            registered = True
                            break
                    except Exception:
                        if attempt == 0:
                            import time
                            time.sleep(1)  # Brief retry delay

                if not registered:
                    print("[pegify] Warning: daemon not reachable — agent registration skipped")

                # Write recent-registration marker for dedup
                try:
                    recent_file.write_text(yaml.dump({
                        "agent_id": assigned_id,
                        "display_name": assigned_name,
                        "team_spawn": is_team_spawn,
                        "lead": lead_name,
                    }))
                except Exception:
                    pass

            # Auto-detect company from daemon if not set
            if not company_id and project_dir:
                try:
                    req = _auth_request("http://127.0.0.1:7654/companies")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        for comp in json.loads(resp.read().decode()):
                            pp = comp.get("project_path", "")
                            if pp and project_dir.startswith(pp):
                                company_id = comp["id"]
                                company_name = comp.get("name", "")
                                break
                except Exception:
                    pass
            elif company_id:
                try:
                    req = _auth_request(f"http://127.0.0.1:7654/companies/{company_id}")
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        company_name = json.loads(resp.read().decode()).get("name", "")
                except Exception:
                    pass

            # Write session identity file
            session_file.write_text(yaml.dump({
                "agent_id": assigned_id,
                "display_name": assigned_name,
                "channel": channel,
                "session_id": session_id,
                "project": project_dir,
                "team_spawn": is_team_spawn,
                "lead": lead_name,
                "company_id": company_id,
            }))

            # Update project agent registry — remember which agents work on this project
            if project_dir and assigned_id:
                try:
                    home = os.environ.get("PEGIFY_HOME", os.path.expanduser("~/.pegify"))
                    projects_dir = Path(home) / "projects"
                    projects_dir.mkdir(parents=True, exist_ok=True)
                    project_reg = projects_dir / f"{project_dir.replace('/', '_').strip('_')}.yaml"
                    proj_data = {}
                    if project_reg.exists():
                        proj_data = yaml.safe_load(project_reg.read_text()) or {}
                    agents_list = proj_data.get("agents", [])
                    # Update or append this agent
                    found = False
                    for a in agents_list:
                        if a.get("agent_id") == assigned_id:
                            a["name"] = assigned_name
                            found = True
                            break
                    if not found:
                        agents_list.insert(0, {"agent_id": assigned_id, "name": assigned_name})
                    proj_data["agents"] = agents_list
                    proj_data["project"] = project_dir
                    proj_data["channel"] = channel
                    project_reg.write_text(yaml.dump(proj_data, default_flow_style=False))
                except Exception:
                    pass

        # Register live session
        try:
            ls_body = json.dumps({
                "session_id": session_id,
                "agent": assigned_name,
                "channel": channel,
                "project": project_dir,
                "adapter": "claude-code",
            }).encode()
            req = _auth_request(
                "http://127.0.0.1:7654/live-sessions/register",
                data=ls_body,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    # Sync profile from .pegify.yaml to daemon (soul, goal, capabilities)
    profile_fields = {}
    for field in ("soul", "goal", "capabilities"):
        val = identity.get(field)
        if val:
            profile_fields[field] = val
    if profile_fields and assigned_name:
        try:
            prof_body = json.dumps(profile_fields).encode()
            req = _auth_request(
                f"http://127.0.0.1:7654/agents/{assigned_name}/profile",
                data=prof_body,
                headers={"Content-Type": "application/json"},
            )
            req.method = "PUT"
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

    # Print identity — company-aware format
    agent_role = agent_info.get("role", "dev") if agent_info else "dev"
    if company_name:
        print(f"[pegify] {assigned_name} ({agent_role}) — {company_name} ({assigned_id})")
    elif is_team_spawn and lead_name:
        print(f"[pegify] {assigned_name} on {channel} ({assigned_id}) — teammate of {lead_name}")
        print(f"[pegify] Coordinate via pegify before making changes. Run `pegify context` for lead's activity.")
    else:
        print(f"[pegify] {assigned_name} on {channel}" + (f" ({assigned_id})" if assigned_id else ""))

    # Show report chain if agent has a manager
    if assigned_id:
        try:
            req = _auth_request(f"http://127.0.0.1:7654/org/{assigned_id}/chain")
            with urllib.request.urlopen(req, timeout=1) as resp:
                chain = json.loads(resp.read().decode())
                if len(chain) > 1:
                    manager = chain[1]
                    print(f"[pegify] Reports to: {manager['name']} ({manager['role']})")
        except Exception:
            pass

    # Register agent inbox for real-time message delivery
    try:
        body = json.dumps({"channels": [channel]}).encode()
        req = _auth_request(
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

    # Load approval mode from Pegify config
    approval_mode = "smart"
    try:
        pegify_config_path = Path(os.environ.get("PEGIFY_HOME", Path.home() / ".pegify")) / "config.yaml"
        if pegify_config_path.exists():
            pegify_config = yaml.safe_load(pegify_config_path.read_text()) or {}
            approval_mode = pegify_config.get("approval", {}).get("mode", "smart")
    except Exception:
        pass

    print(f"[pegify] Approval mode: {approval_mode}")

    # Fetch agent briefing — soul, goal, teammates, rules, recent context
    project_qs = f"?project={project_dir}" if project_dir else ""
    try:
        req = _auth_request(f"http://127.0.0.1:7654/agents/{assigned_name}/briefing{project_qs}")
        with urllib.request.urlopen(req, timeout=3) as resp:
            briefing = json.loads(resp.read().decode())
            profile = briefing.get("profile", {})
            soul = profile.get("soul", "")
            goal = profile.get("goal", "")
            capabilities = profile.get("capabilities", "")
            teammates = briefing.get("teammates", [])
            rules = briefing.get("rules", [])

            if soul:
                print(f"[pegify] Soul: {soul}")
            if goal:
                print(f"[pegify] Goal: {goal}")
            if capabilities:
                print(f"[pegify] Capabilities: {capabilities}")
            if teammates:
                names = [f"{t['name']} ({t['state']})" for t in teammates]
                print(f"[pegify] Teammates: {', '.join(names)}")
            if rules:
                print(f"[pegify] Rules:")
                for r in rules:
                    print(f"  [{r['scope']}] {r['rule']}")
    except Exception:
        pass  # Daemon may not be running

    print()
    print(f'[pegify] To contact the user, run: pegify say {channel} "your message"')
    print("[pegify] Cross-session memory: use `pegify memory` commands for shared context.")
    print("The user may be away from this terminal. Use Pegify for all communication.")


if __name__ == "__main__":
    main()
