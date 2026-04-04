---
name: approval
description: Set Pegify approval mode (auto/smart/strict). Usage /pegify:approval auto
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash(pegify *)
  - Read
---

# /pegify:approval — Set Approval Mode

Arguments: $ARGUMENTS

Run: `pegify approval set $ARGUMENTS`

If no arguments provided, run: `pegify approval status`

Show the result to the user. Keep it brief.
