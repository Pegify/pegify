---
name: rename
description: Rename your Pegify agent identity. Usage /pegify:rename "NewName"
---

Rename your Pegify agent to the name provided as the argument.

1. Read your current identity from `~/.pegify/sessions/*.yaml`
2. Call the rename API:
```bash
curl -s -X POST "http://127.0.0.1:7654/agents/CURRENT_NAME/rename" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "NEW_NAME"}'
```
Replace CURRENT_NAME with the `display_name` from your session file, and NEW_NAME with the argument the user provided.

3. Update the session identity file with the new name
4. Print: `✓ OldName → NewName`

If the rename fails (name taken), print the error from the API response.
