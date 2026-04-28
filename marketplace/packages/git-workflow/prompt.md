# Git Workflow

## Non-negotiable rules
1. **Never commit to main/master.** Always create a feature branch first.
2. **One logical change per commit.** If you need "and" in the commit message, split it.
3. **Commit message format:** `type(scope): short description` — feat, fix, chore, docs, test, refactor.
4. **PR for every change.** No direct pushes to main, even for "tiny" fixes.
5. **Green before merge.** No merging with failing tests or type errors.

## Branch naming
`{yourname}/{short-description}` — e.g., `nova/fix-auth-timeout`

## Commit message body (when needed)
First line: summary (72 chars max). Blank line. Then: the WHY (not the what — the diff shows the what).

## Before opening a PR
- [ ] `git diff main...HEAD` — review every line
- [ ] All tests pass locally
- [ ] No debug code, no commented-out blocks, no TODO left behind
