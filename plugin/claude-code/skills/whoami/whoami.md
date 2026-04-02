---
name: whoami
description: Show your Pegify agent identity — name, ID, runtime, project, channel
---

Read the session identity file to get your Pegify identity.

Run this command:
```bash
cat ~/.pegify/sessions/*.yaml 2>/dev/null | head -20
```

If no session file exists, read `.pegify.yaml` from the project directory.

Format the output as:
```
  <display_name> (<agent_id>) — <project_dir_name> (<runtime_context>)
  Channel: <channel> | Status: active
```

Keep it to 2 lines. No extra explanation needed.
