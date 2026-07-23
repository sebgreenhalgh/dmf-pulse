# Contributing to DMF Pulse

Work from an approved ticket on a scoped branch. Read `AGENTS.md`, the ticket, authority manifest, relevant DMFP sections, and accepted/provisional decision states before editing.

For every change:

1. Update `PLANS.md` when work is nontrivial.
2. Preserve public contracts unless the ticket explicitly changes them.
3. Add independent tests for successful and failing behaviour; keep tests offline and isolated from the user home.
4. Do not add a dependency, migration, service, domain stub, provider call, or `.env` design without explicit authority. DAT-003 migrations must be reversible against PostgreSQL 18.4 and enforce temporal and immutability invariants in the database.
5. Run the literal format, lint, mypy, branch-coverage, build, wheel, repository, and secret-scan commands in `README.md`.
6. Record exact acceptance evidence and review security/scope before requesting review.

Use conventional, focused commit messages when the owner requests commits. Codex must not push, merge, rebase, reset, tag, amend prior commits, rewrite history, or change repository visibility for DAT-003.
