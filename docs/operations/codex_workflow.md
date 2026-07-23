# Codex ticket workflow

1. Capture the repository baseline before any edit.
2. Resolve the active ticket through the authority and decision manifests, preserving statuses.
3. Maintain timestamped checkpoints in `PLANS.md`.
4. Build tests/contracts alongside each runnable slice.
5. Run targeted checks, then the literal acceptance suite from the frozen uv environment.
6. Obtain fresh read-only scope/security/test review and fix material findings.
7. Generate schema-valid ticket evidence and a deterministic review ZIP of at most 20 root files.
8. Hand the branch, repository, evidence, and ZIP to the human owner. Only the human review process may approve merge/tag/release.

Codex must not push, merge, rebase, reset, tag, amend prior commits, rewrite history, change repository visibility, read secrets, or contact providers/production services under DAT-003. PostgreSQL use is limited to the disposable 18.4 test service, and teardown must run even after failure.
