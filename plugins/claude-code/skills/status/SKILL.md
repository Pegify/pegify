---
name: status
description: Show Pegify daemon status, channel info, connected clients, and pending approvals
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash(pegify *)
  - Bash(curl *)
  - Read
---

# /pegify:status — System Status

Show comprehensive Pegify system status.

## Daemon
Run: `pegify daemon status`

## Health check
Run: `curl -s http://localhost:7654/health`

## Channel info
Read `.pegify.yaml` for the configured channel, then: `pegify channel status <channel>`

## Pending approvals
Run: `pegify approve list`

Display all results in a clear format.
