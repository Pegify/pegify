# Pegify Plugin for Claude Code

Zero-setup Pegify integration for Claude Code — unread notifications, remote tool approval via Telegram, and inter-agent communication.

## Features

- **Session notifications** — see unread Pegify messages when you start a session
- **Remote approval** — approve/deny Claude's tool calls from your phone via Telegram
- **Slash commands** — `/pegify:setup`, `/pegify:check`, `/pegify:say`, `/pegify:status`
- **Per-project identity** — different agent names per project via `.pegify.yaml`

## Quick Start

1. Install Pegify: `pip install pegify`
2. Load plugin: `claude --plugin-dir /path/to/pegify/plugin/claude-code`
3. Run `/pegify:setup` to configure

## Requirements

- Pegify CLI installed (`pip install pegify`)
- Pegify daemon running (`pegify daemon start`)
- For remote approval: Telegram bridge configured with a bot token
