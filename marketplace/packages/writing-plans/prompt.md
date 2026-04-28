# Writing Implementation Plans

Plans must be executable by someone with zero codebase context.

## Rules
- **Exact file paths.** Never "the config file" — always `src/config/settings.py`.
- **Complete code in every step.** If a step changes code, show the full new version.
- **Exact commands with expected output.** `pytest tests/test_foo.py -v` → `PASSED`.
- **No placeholders.** Never write "TBD", "add error handling", or "similar to above".
- **One action per step.** Write test → run test → implement → run test → commit.
- **DRY and YAGNI.** No future-proofing. No abstractions beyond the immediate task.

## Task Structure

```
### Task N: [Name]
**Files:** Create: `path/to/file.py` | Modify: `path/to/existing.py:L10-L25`

- [ ] Write failing test
- [ ] Run: `pytest tests/test_x.py::test_name -v` — Expected: FAIL "not defined"
- [ ] Implement minimal code
- [ ] Run: `pytest tests/test_x.py::test_name -v` — Expected: PASS
- [ ] `git commit -m "feat: ..."`
```
