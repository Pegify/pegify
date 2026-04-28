# TDD — Test-Driven Development

Always follow this cycle:

1. **Write the failing test first.** No implementation code until the test exists.
2. **Run it and confirm it fails** for the right reason (not an import error — the tested behavior is missing).
3. **Write the minimal implementation** to make the test pass. Nothing more.
4. **Run tests.** All must be green before committing.
5. **Commit.** One small commit per green cycle.

Never write implementation code before its test. Never commit red tests. If you find yourself implementing without a failing test, stop and write the test first.
