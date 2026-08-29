# Test Database Safety Template

Use this section in project docs when a database is introduced.

- Development database variable: `<DATABASE_URL or equivalent>`
- Test database variable: `<TEST_DATABASE_URL or equivalent>`
- Test reset command: `<safe command>`
- Safety assertion before reset: `<how the test harness proves it is a test DB>`
- Production protection: `<how prod credentials/data are excluded>`

A destructive reset MUST abort if the target cannot be proven to be test-only.
