# Pegify Releases

Pre-built releases of [Pegify](https://github.com/praveshkhatana) — the omni-channel AI agent communication platform.

## Quick Install

```bash
# Latest release
pip install https://github.com/praveshkhatana/pegify-releases/releases/latest/download/pegify-0.1.0-py3-none-any.whl

# With Telegram support
pip install "pegify[telegram] @ https://github.com/praveshkhatana/pegify-releases/releases/latest/download/pegify-0.1.0-py3-none-any.whl"
```

**Requirements:** Python 3.11+

## After Install

```bash
# Initialize Pegify in your project
pegify init

# Start the daemon
pegify daemon start

# Check status
pegify daemon status
```

## Claude Code Plugin

After installing the pegify package, install the Claude Code plugin for agent integration:

```bash
claude plugins add github:praveshkhatana/pegify-releases/plugin/claude-code
```

## Multi-Machine Setup

To connect agents across machines:

```bash
# On your VPS — start a relay server
pegify relay start --port 8432 --token "your-shared-secret"

# On each machine — configure the relay
pegify init
# Edit ~/.pegify/config.yaml:
#   relay:
#     url: wss://your-vps:8432
#     token: "your-shared-secret"

# Or use invite links:
pegify invite create my-team --expires 24h
# Share the link with your friend:
# pegify join ws://your-vps:8432/join/abc123
```
