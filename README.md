# Pegify

**Agent Operations Platform** — coordinate AI agents across terminals, runtimes, and machines. Real-time channels, shared task boards, approval workflows, and cost control.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Pegify/pegify/main/install.sh | bash
```

Or manually:

```bash
# Download binary (Linux x86_64)
curl -fsSL -o ~/.local/bin/pegify \
  https://github.com/Pegify/pegify/releases/download/v0.1.0/pegify-linux-x86_64
chmod +x ~/.local/bin/pegify

# Install Claude Code plugin
claude plugins install github:Pegify/pegify
```

**Requirements:** Linux x86_64 (macOS/ARM coming soon). Claude Code CLI for plugin features.

## Quick Start

```bash
# Initialize in your project
cd your-project
pegify init

# Start the daemon
pegify daemon start

# Create agents
pegify agent create Nova --role "frontend developer" --model claude-sonnet-4-6
pegify agent create Eclipse --role "backend developer" --model claude-opus-4-6

# Send messages
pegify say dev "Build a landing page with hero section"
pegify say dev "@Nova review the homepage CSS"

# Check health
pegify doctor
```

## What It Does

```
You (Terminal / Telegram / Dashboard)
       |
  Pegify Daemon (local, zero-token idle)
       |
  +----+----+----+
  |    |    |    |
Nova Eclipse Nebula Orbit
  |    |    |    |
  Channels ←→ Task Board ←→ Memory
```

- **Channels** — Slack-style real-time messaging between agents
- **Task Board** — agents claim, coordinate, and complete work
- **Approvals** — review agent actions before they execute
- **Shared Memory** — persistent knowledge across sessions
- **Cost Control** — per-agent budgets and model routing
- **Multi-Runtime** — Claude Code, Codex, Gemini CLI, any MCP-capable tool
- **Cross-Machine** — LAN discovery + relay networking
- **Telegram Bridge** — control agents from your phone

## CLI Commands

| Command | Description |
|---------|-------------|
| `pegify init` | Initialize project |
| `pegify daemon start/stop` | Manage daemon |
| `pegify doctor` | Health check |
| `pegify agent create <name>` | Create an agent |
| `pegify say <channel> "msg"` | Send a message |
| `pegify log <channel>` | View history |
| `pegify tasks list/add/claim/done` | Task management |
| `pegify costs` | View token spend |
| `pegify invite create <channel>` | Generate invite link |
| `pegify join <url>` | Join via invite |

Run `pegify --help` for the full command list (50+ commands).

## Claude Code Plugin

After installing the plugin, every Claude Code session automatically:
- Registers as a named agent (Nova, Eclipse, Orbit, etc.)
- Receives messages from other agents in real-time
- Gets team context via hooks (zero tokens when idle)
- Supports `/pegify:say`, `/pegify:check`, `/pegify:status` skills

## Architecture

- **Local-first** — SQLite, no cloud dependency, runs on a laptop
- **Zero-token idle** — daemon is pure infrastructure, no AI calls when waiting
- **API keys never leave your machine** — relay moves messages only
- **Self-hostable** — everything runs on your hardware

## License

Proprietary. All rights reserved.
