# Systematic Debugging

**Iron law: find root cause before attempting any fix.**

## Phase 1 — Root Cause
1. Read the full error message and stack trace. Note the exact file and line.
2. Reproduce it reliably. If you cannot reproduce it, gather more data.
3. Check recent changes (git diff). What changed that could cause this?
4. Add instrumentation at each component boundary to see where bad data enters.
5. Trace backwards from the symptom to the origin.

## Phase 2 — Hypothesis
State clearly: "I believe X is the root cause because Y." One hypothesis at a time.

## Phase 3 — Minimal Fix
Make the smallest possible change to test the hypothesis. One variable at a time.
If three fixes have failed, stop. Question the architecture, not the fix.

## Red Flags (stop immediately if you think these)
- "Quick fix for now, investigate later"
- "Just try changing X and see"
- "I don't fully understand but this might work"
