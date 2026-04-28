# Code Review

Review in this order. Stop at Critical — don't add nice-to-haves when there are blockers.

## Critical (must fix before merge)
- Correctness bugs: wrong logic, off-by-one, null dereference
- Security: SQL injection, XSS, insecure deserialization, secrets in code
- Data loss: writes that overwrite without backup, destructive migrations without guard
- Broken tests or missing tests for the changed behavior

## Important (should fix)
- Unclear variable/function names that require a comment to understand
- Missing error handling at system boundaries (user input, external APIs)
- Duplication that will cause bugs when one copy is updated but not the other

## Minor (optional)
- Style inconsistencies
- Nitpicks on naming

## Format
List findings under each tier. For each: file:line, what's wrong, suggested fix. End with overall verdict: APPROVED / NOT APPROVED / APPROVED WITH FIXES.
