# DAT-003 definition of ready

- Required baseline and branch match the ticket and the worktree is clean at preflight.
- Pack 003 and fixture hashes validate; governing DMFP documents and decisions have no material conflict.
- Docker Compose can run the pinned `postgres:18.4-bookworm` image and PostgreSQL reports `uuidv7()`.
- Only the three approved pinned runtime dependencies are added; PostgreSQL integration is real, disposable, and offline from providers.
- RUL-002 corrected v1.1 goldens are immutable inputs and each mandatory remediation has an independent regression test.
- Public CLI, schema, temporal, provenance, migration, exclusion, security, acceptance, and 20-file review contracts are understood.
