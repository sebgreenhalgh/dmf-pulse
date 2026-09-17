# R9C-A2 command ledger

This ledger records synthetic/offline engineering validation only. No live provider result,
private entry identifier, provider body, player history, posterior row, credential, market fact or
decision-level live observation may be written here.

The immutable parent is `f6c3bbf0c768ca83d2b4b993425fb5ff7f6e7ef7`; parent exact-SHA CI
`35224587426` completed successfully.

## Offline implementation checkpoint

- `uv sync --all-groups --frozen` - PASS.
- A2 authority, preparation, safe-failure and real four-world comparison suite - PASS
  (33 tests in 265.70 seconds).
- A1.01/A1.02/A1.03 plus R9A/R9B history, posterior and shadow regression - PASS
  (120 tests in 241.80 seconds).
- Complete selected private-v1, one-command and transient-provider regression - 234 tests PASS;
  six PostgreSQL security cases were not runnable because `DMF_TEST_DATABASE_URL` was absent.
  These were fixture-setup errors, not test failures.
- Complete Stage 9, Stage 10 and Stage 11 unit/contract/golden regression - PASS
  (622 tests in 575.99 seconds).
- Complete unit ingestion regression - PASS (1,148 tests in 160.94 seconds).
- Branch-enabled focused A2 run - PASS (15 tests in 625.51 seconds); the new
  `live_shadow_observation.py` module reports 91% coverage. The combined focused whole-file report
  for A2 plus inherited `one_command.py` and `shadow_adapter.py` is 83%, because the focused run
  does not traverse substantial pre-existing branches; that combined report is not represented as
  satisfying the repository-wide 90% threshold.
- `uv run ruff format --check .` - PASS (825 files already formatted).
- `uv run ruff check .` - PASS.
- `uv run mypy src/dmf_pulse` - PASS (294 source files).
- `uv run python scripts/scan_secrets.py` - PASS (zero findings) after replacing one direct
  synthetic credential literal with the repository's established named-marker fixture pattern.
- `uv build` - PASS; built `dmf_pulse-0.2.0` sdist and wheel.
- Isolated wheel import of the A2 module - PASS. Installed CLI help - PASS with the frozen
  Typer 0.27.0 dependency. An unconstrained install selected Typer 0.27.2 and failed CLI import;
  that non-frozen dependency result is disclosed and is not represented as a pass.
- `uv run python scripts/verify_fpl004_wheel.py` was not runnable because
  `DMF_TEST_DATABASE_URL` was absent; the clean wheel import/CLI check above is database-free.
- `uv sync --all-groups --frozen` - PASS (40 packages checked, no lock mutation).
- Canonical `PRC-013` repository manifest regenerated with 1,425 files.
- Unit/integration repository manifest validation - PASS (8 tests in 2.50 seconds).
- `uv run python scripts/validate_repository.py` - PASS (zero errors).
- `git diff --check` - PASS.

All commands above used synthetic or repository-owned inputs. No live provider request, credential
inspection, private entry execution, live persistence, training, calibration or activation occurred.
The independent engineering verdict is returned separately after this final candidate is frozen;
it is not written into this file after review. No live command is part of pre-publication evidence.

## Independent-review remediation

The first independent engineering review returned `NOT CLEAR_FOR_PUSH_AND_EXACT_SHA_CI` with two
P1 and two material P2 findings: cutoff checks did not guard every provider boundary/attempt;
preflight Odds authority checks were weaker than the governed metadata gate; three existing
control hashes were omitted; and the zero-network result relied only on local counters without a
global denial test.

Remediation adds a default-off per-attempt FPL guard, A2-only provider-phase/final-seal guards,
exact status/purpose/account/geography/terms/timestamp authority checks plus canonical capability
decisions before any client, fixture-order/terminal-policy/candidate-policy controls, measured
network deltas, global socket/provider-construction denial tests, and a closed safe-summary failure
path. Ordinary construction supplies none of the private hooks.

- Remediated A2/FPL/rights suite - PASS (63 tests in 325.44 seconds).
- Cutoff/authority focused suite - PASS (14 tests); cutoff crossing after bootstrap retained one
  completed transport and prevented every later provider construction/request.
- Direct-FPL retry guard test - PASS; expiry before retry left one transport call.
- Ordinary one-command, score-prefetch and current assembly regression - PASS
  (21 tests in 348.76 seconds).
- A1.01/A1.02/A1.03 and R9A/R9B regression after remediation - PASS
  (120 tests in 333.41 seconds).
- Complete unit ingestion after remediation - PASS (1,148 tests in 256.77 seconds).
- Exact-candidate branch-enabled A2 run - PASS (26 tests in 828.94 seconds); new A2 module 91%.
  The focused combined report is 75% because it includes large inherited `direct.py`,
  `one_command.py`, and `shadow_adapter.py` files outside the focused traversal; it is not
  represented as satisfying the repository-wide threshold.

No live provider, credential, private-entry or persistence action occurred during remediation.

The remediation re-review confirmed those original findings were closed, then identified three
remaining issues: the acquisition window lacked its approval-time lower bound; the reconstructed
score-prior service had no per-resource cutoff guard; and the exact FPL preflight omitted three
governed metadata fields. The final candidate enforces
`operator_approved_at <= acquisition_time <= acquisition_cutoff`, adds a default-off guard
immediately before each score-prior resource transport, and seals the FPL terms source,
unresolved-rights set, and termination-deletion flag before provider construction.

- Focused lower-bound, FPL-tamper, cutoff/retry and score-resource guard tests - PASS (14 tests).
- Complete OpenFootball plus A2 preparation/comparison regression - PASS
  (162 tests in 268.70 seconds).
- Final branch-enabled A2 run - PASS (33 tests in 602.31 seconds); the A2 module reports 92%
  coverage. Appending the complete OpenFootball suite (129 tests) gives 95% for its affected
  service and 93% across both changed modules.
- Ruff format/check and strict mypy (294 source files) after the final remediation - PASS.

No live provider, credential, private-entry or persistence action occurred during final
remediation. The final independent verdict is obtained against the frozen candidate and recorded
in the handoff, not inferred from this implementation ledger.
