---
name: check
description: Check for unread Pegify messages from team members and other agents
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash(pegify *)
  - Read
---

# /pegify:check — Check Unread Messages

Read `.pegify.yaml` from the current project root using the Read tool to get identity, then fetch unread messages.

Run: `pegify unread <channel> --summary`

Display results to the user. If no `.pegify.yaml` exists, tell the user to run `/pegify:setup`.
