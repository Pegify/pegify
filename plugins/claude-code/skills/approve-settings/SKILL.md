---
name: approve-settings
description: Configure remote approval behavior — timeout, default action, approval channel
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - Read
  - Write
---

# /pegify:approve-settings — Configure Approvals

Read the current `.pegify.yaml` using the Read tool.

Show current approval settings and ask what to change:
- **enabled**: true/false
- **channel**: which channel for approval messages (default: claude-approvals)
- **timeout**: seconds to wait for response (default: 600)
- **timeout_action**: what to do on timeout — deny, ask, or allow (default: ask)

After the user specifies changes, update `.pegify.yaml` using the Write tool.

If `.pegify.yaml` doesn't exist, tell the user to run `/pegify:setup` first.
