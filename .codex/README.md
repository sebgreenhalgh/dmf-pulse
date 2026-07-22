# Codex workflow

Codex work in this repository is ticket-scoped and human-reviewed. Start with `AGENTS.md`, `PLANS.md`, the active `tickets/<id>/ticket.yaml`, and the authority/decision manifests. Load only the directly relevant approved specification sections; do not serially summarize the full corpus.

- `prompts/implement_foundation.txt` constrains an implementation session.
- `prompts/review_ticket.txt` drives a fresh read-only review.
- `schemas/codex_result.schema.json` and `schemas/review_manifest.schema.json` are checked-in public evidence contracts.

No prompt grants authority to read secrets, call providers, mutate remotes, merge, tag, or implement beyond the active ticket. A Codex completion result is evidence for human review, not human acceptance.
