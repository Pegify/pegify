---
name: setup
description: Set up Pegify integration — identity, channel, daemon, and remote approvals. Run this first before using other Pegify features.
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - Bash(pegify *)
  - Bash(pip install *)
  - Bash(which pegify)
  - Bash(curl *)
  - Read
  - Write
---

# /pegify:setup — Guided Setup Wizard

Walk the user through Pegify setup step by step. Ask one question at a time.

## Step 1: Check prerequisites

Check if pegify CLI is installed: `which pegify`
If not found, install: `pip install pegify`
Check if ~/.pegify exists: read `~/.pegify/config.yaml`
If not found: run `pegify init`

## Step 2: Channel setup

List existing channels: `pegify channel list`
Ask the user which channel to use. If they want a new one: `pegify channel create <name>`

## Step 3: Identity setup

Ask for the agent name (e.g., "claude-backend", "claude-frontend").
Join the channel: `pegify channel join <channel> <agent-name>`
Set global default: `pegify whoami set --default <channel> <agent-name>`
Write `.pegify.yaml` in the current project root with agent + channel.

## Step 4: Remote approval setup

Ask if the user wants remote approvals enabled (recommended if they'll be away from terminal).
If yes:
- Ask for approval channel name (default: `claude-approvals`)
- Create it if needed: `pegify channel create claude-approvals`
- Ask for timeout action: deny, ask (default), or allow
- Ask for timeout duration in seconds (default: 600)
- Update `.pegify.yaml` with approval config

## Step 5: Daemon check

Run `pegify daemon status`. If not running, ask if user wants to start it.
Verify: `curl -s http://localhost:7654/health`

## Step 6: Verification

Send a test message: `pegify say <channel> "Pegify plugin setup complete for <agent-name>"`

## Step 7: Gitignore

Check if `.pegify.yaml` is in `.gitignore`. Recommend adding it since it contains per-developer agent identity.
