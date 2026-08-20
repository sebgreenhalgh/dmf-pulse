# RANK-015 independent Sol review

## Review identity

- Review date: `2026-08-20`.
- Immutable implementation parent: `c53a1dfae952f481c1e885200ebf6120e4b63c24`.
- Exact pre-review branch SHA: `17b6aa576459c652e14015dcfd7b7cf0bffd6f9d`.
- Actual starting remote SHA: `17b6aa576459c652e14015dcfd7b7cf0bffd6f9d`.
- Merge base with `origin/main`: `c53a1dfae952f481c1e885200ebf6120e4b63c24`.
- Near-final `origin/main`: `c53a1dfae952f481c1e885200ebf6120e4b63c24`.
- Main integration: `NO_MAIN_INTEGRATION_REQUIRED`.
- Engineering status: `REVIEW_READY_PENDING_HUMAN_ACCEPTANCE`.
- Human acceptance: `false`.
- Merge/tag: none.

The supplied Stage-15 context files were read in full and reconciled byte-for-byte with the
approved repository copies. The complete immutable-parent Stage-15 diff, all six checkpoints,
public contracts, tests, independent oracles, artifacts and CLI paths were reviewed directly;
prior checkpoint evidence was not treated as proof.

## Independent findings and remediation

No P0 defect was found. No P0, P1 or material P2 finding remains unresolved.

| ID | Severity | Finding | Remediation and regression |
|---|---|---|---|
| SOL-RANK-001 | P1 | Exact mini-league accepted mutated nested multiplier records/sets and an out-of-population target. | Verify both semantic hash layers before rank arithmetic, bind exact tie-policy identity, reject sentinel lineage and invalid targets; add nested/set tamper, target-bound and tie-policy regressions. |
| SOL-RANK-002 | P1 | Exact rank distributions could be semantically resealed with a PMF, percentile or median surface inconsistent with scenario outcomes. | Derive PMF, expected/median/percentile rank and P(target) from exact outcomes; revalidate sealed output and reject resealed mismatch. |
| SOL-RANK-003 | P1 | Stage-9 raw-projection identity omitted model/dataset/source/upstream lineage. | Hash the complete immutable `GameweekScenarioSet`; add model-version and Stage-8-lineage sensitivity tests while proving the shared football-draw identity is unchanged. |
| SOL-RANK-004 | P1 | Joint rival-action composition accepted a stale source distribution hash. | Verify/revalidate every source distribution and the final joint hash; add stale-source rejection. |
| SOL-RANK-005 | P1 | Secure/unreachable targets could choose a lower-points plan on an expected-rank tie breaker with zero P(target) gain; population surfaces were not compared. | Add `TARGET_NOT_DECISION_SENSITIVE`, target-population bounds and common population/tie-policy checks with secure, unreachable, outside-population and mismatch regressions. |
| SOL-RANK-006 | P1 | Stage-13 activation statuses were dropped at the Stage-15 service boundary, and Stage-13/14 source plans did not require matching lineage components. | Bind the complete status inventory into request/result hashes, degrade limited states, propagate price-rights blocking and require source-stage lineage; add status and missing-inventory/component regressions. |
| SOL-RANK-007 | P1 | Free Hit and Wildcard rival actions could carry ordinary transfer-hit deductions. | Reject hits on both chip paths; add two chip-specific regressions. |
| SOL-RANK-008 | P2 | Synthetic rank percentiles and median were not independently reconciled to the PMF. | Derive all canonical quantiles from the PMF and add value/median tamper guards. |
| SOL-RANK-009 | P2 | Bench Boost scoring was correct, but diagnostics could retain autosub events that do not execute under the chip transform. | Emit no autosub events under Bench Boost and assert the diagnostic contract. |
| SOL-RANK-010 | P2 | Several produced multiplier/EO objects were sealed through unchecked model copies. | Revalidate final sealed objects and reject zero protected lineage hashes. |

Thirty-one new parameter-expanded regression cases were added, with additional assertions in
existing chip, synthetic and artifact tests. P3 findings: none.

## Independent results

- Complete Stage-15 matrix: `274 passed in 11.19s`.
- Raw branch coverage: `861/954 = 90.251572327044%`.
- Combined line/branch coverage: `94.331983805668%` (not substituted for raw coverage).
- Targeted inherited Rules and Stages 9-14 matrix: `37 passed in 5.41s` using the exact nodes and
  rationales already listed in `FINAL_ACCEPTANCE.md`.
- Projection invariance: PASS for all seven objectives; candidate objects, scenario-score hashes
  and the complete Stage-9 raw-projection hash remained identical.
- Shared football worlds: PASS for exact named rivals, every hidden action, joint rivals and the
  synthetic field; scenario IDs, draw IDs, weights, scenario-set hashes and raw hashes reconcile.
- EO/multipliers: PASS; weighted counted multipliers, conditional vice, TC, BB, FH and autosubs
  reconcile; EO above 100% remains valid and ownership is not utility.
- Exact mini-league oracle: PASS for two, three and multi-manager cases; the oracle imports no
  production mini-league/rank simulator.
- Opponent model: PASS; probability/marginal, cutoff, rights, identity, uncertainty, non-clone,
  transfer/chip and temporal gates reconcile.
- Rank/target utility: PASS; explicit epsilon/lexicographic policy, PMF-derived P(target), points
  floor and target sensitivity all reconcile.
- Synthetic-field oracle: PASS; the known-truth oracle imports neither production synthetic-field
  service nor rank-simulator helpers.
- Service/fallback: PASS; accepted Stage-12/13/14 plans are re-evaluated without invoking upstream
  optimisers, the points optimum is retained, and required failures select `PURE_POINTS`.
- Artifact/tamper: PASS for detached, outer, nested, plan, PMF, probability, selected-plan, gate,
  confidence, rights, cutoff and projection/scenario lineage protection.
- Rights/privacy: PASS; no population scraper, final-rank hindsight path or definitive calibrated
  overall-win claim exists.
- Full repository pytest: `RESOURCE_LIMIT` (the one bounded attempt exited `124` after
  `1204.026s` without emitting a test failure; its remaining process tree was explicitly stopped;
  the unchanged full suite was not rerun).
- `uv sync --all-groups --frozen`: PASS (`Checked 40 packages`).
- Ruff format: PASS (`635 files already formatted`).
- Ruff lint: PASS.
- Strict mypy: PASS (`245 source files`).
- `git diff --check`: PASS.
- Hatchling build: PASS (`dmf_pulse-0.2.0.tar.gz` and
  `dmf_pulse-0.2.0-py3-none-any.whl`).
- Clean external-wheel CLI: PASS with source-tree `PYTHONPATH` cleared; version, rank help, all
  rank subcommand helps and `dmf rank validate` ran from the installed wheel. The disposable
  wheel environment was removed afterward.
- Final-tree hygiene: PASS. No Stage-15 publisher/finalizer workflow, recovery/payload material,
  trigger marker, local path or secret remains in the repository tree. An ACL-inaccessible
  test-created `.test-tmp` directory was moved out of the repository to the explicitly named OS
  temp path `C:\Users\sebgr\AppData\Local\Temp\dmf-pulse-stage15-test-tmp-20260820`.

- Governed repository manifest refresh: PASS (`1126` tracked files recorded).
- Repository validation: PASS (`error_count: 0`).
- First-party secret scan: PASS (`finding_count: 0`).

Draft PR identity is recorded after remote publication. Human acceptance and merge remain separate
and pending.

## Verdict

`PASS_WITH_NONBLOCKING_LIMITATIONS`

Nonblocking limitations are the explicitly approximate synthetic overall cohort, prospective rank
performance/calibration not yet established, inherited target-season price limitations propagated
from Stage 13, conditional lawful cohort/opponent availability, and the resource-limited broad
repository pytest attempt. These do not bypass the production fail-closed gates.
