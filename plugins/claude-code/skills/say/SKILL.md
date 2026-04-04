---
name: say
description: Send a message to the team via Pegify channel. Usage /pegify:say "your message"
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash(pegify *)
  - Read
---

# /pegify:say — Send a Message

Arguments: $ARGUMENTS

Read `.pegify.yaml` from the current project root using the Read tool to get identity and channel.

Send the message: `pegify say <channel> "$ARGUMENTS"`

If no arguments provided, ask what message to send.
If no `.pegify.yaml` exists, tell the user to run `/pegify:setup`.
