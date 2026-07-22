# RUL-002 Acceptance Contract

## Gate A — foundation remediation

The following are merge-blocking:

- `AGENTS.md` and the machine authority manifest preserve the exact DMFP-20 precedence.
- Active ticket contracts are explicitly subordinate to official rules/provider terms, approved ADRs and accepted module specifications.
- `decision_manifest.json` is generated from the complete DMFP-20 ADR register, not a hand-selected authority substitute.
- Every A2–B7 authority scope passes a required-minimum documents/ADRs validator.
- Evidence/review tooling accepts at least `FND-001` and `RUL-002`, rejects traversal/malformed IDs, and derives paths/names safely.
- FND-001 evidence remains valid.
- COMPLETE evidence requires and stores the actual Git commit.
- Wheel verification derives the version and checks installed runtime distributions against the frozen locked-runtime manifest.

## Gate B — rules compiler

- Split-file YAML uses safe loading and rejects duplicate keys, aliases/anchors, custom tags and invalid scalar types.
- Required files, schemas, controlled vocabularies, units, verification states and source references validate strictly.
- Canonical JSON output is stable across runs/platform newline/order differences.
- SHA-256 identity is deterministic and stored with source/config version.
- REFERENCE_ONLY and synthetic rules compile.
- CAPTURED_UNVERIFIED target rules can be inspected but activation returns a stable blocking error.
- ACTIVE artifacts are immutable by hash; overwrite/edit-in-place is rejected.

## Gate C — scoring

- Every scenario-level component and BPS is integer.
- Component sum equals fixture total exactly.
- Bonus is allocated jointly from all scenario participants by generic competition ranking.
- Clean sheets derive from score/on-pitch/dismissal state, never a separate arbitrary flag.
- Gameweek total is the exact sum of fixture totals under one ruleset.
- Golden fixtures and tie cases match supplied expected outputs byte-for-byte after canonical JSON serialization.
- Same input/ruleset produces same output/hash.

## Gate D — quality and package

Run and record these exact commands once at final acceptance (plus targeted checkpoint commands):

1. `uv sync --all-groups --frozen`
2. `uv run ruff format --check .`
3. `uv run ruff check .`
4. `uv run mypy src/dmf_pulse`
5. `uv run pytest --cov=dmf_pulse --cov-branch --cov-report=term-missing --cov-report=json:evidence/tickets/RUL-002/coverage.json`
6. `uv run dmf --version`
7. `uv run dmf doctor --json`
8. `uv run dmf rules validate fixtures/rules/RUL-002/synthetic_complete --json`
9. `uv run dmf rules compile fixtures/rules/RUL-002/synthetic_complete --output artifacts/rules/rul-002-synthetic.json --json`
10. `uv run dmf rules hash artifacts/rules/rul-002-synthetic.json --json`
11. `uv run dmf rules score-fixture artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_fixture_001.json --json`
12. `uv run dmf rules score-gameweek artifacts/rules/rul-002-synthetic.json fixtures/rules/RUL-002/golden_gameweek_001.json --json`
13. `uv run dmf rules diff fixtures/rules/RUL-002/reference_2025_26 fixtures/rules/RUL-002/target_2026_27_partial --json`
14. `uv run dmf rules activate fixtures/rules/RUL-002/target_2026_27_partial --approval fixtures/rules/RUL-002/invalid_target_approval.json --json` (must exit with the documented blocked code; record as an expected-pass negative test through the acceptance runner)
15. `uv build`
16. `uv run python scripts/verify_wheel.py`
17. `uv run python scripts/validate_repository.py`
18. `uv run python scripts/scan_secrets.py`
19. `uv run dmf review-pack build --ticket RUL-002 --baseline 12049a7de23a4a8fcca3d219dbcab1bf5e1027ea --output review_pack/RUL-002`

The acceptance runner may represent command 14 with a wrapper/expected-exit assertion, but the underlying CLI invocation and actual exit code must be retained.

Coverage gates:
- overall production-package branch coverage >= 90%;
- `dmf_pulse.rules` branch coverage >= 95%;
- no skipped required golden/property/integration test;
- all critical mutants or equivalent manual mutation probes for activation, ties, thresholds and component summation must be addressed.

## Gate E — review artifact

- clean working tree at final HEAD;
- no push or merge;
- maximum 20 root files;
- full human-authored patch from baseline;
- CRC/checksum validation passes;
- result/evidence records use actual commit and distinguish payload/archive digest.
