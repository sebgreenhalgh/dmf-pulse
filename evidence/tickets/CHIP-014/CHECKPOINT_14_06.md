# CHIP-014 checkpoint 14.06 — finite-inventory chip scheduler

## Recovery disposition

The scheduler commit reported by the terminated session,
`3935bc00ff760a6c76bb6115e142aa273affc371` with expected tree
`54cfb7bc06b7fdf42fe3fd7a754f66ff3490cb77`, was not recoverable from either
available Git object store, reflog, stash list, `git fsck` output, or exported
workspace bundle. The named 14.07 stash was also absent.

Checkpoint 14.06 was therefore completed as a truthful Case B recovery from the
published Wildcard capability. Preserved source remnants from the terminated
workspace were reconciled against the canonical branch, reviewed, extended with
adversarial tests, and validated. This record does not claim recovery of the
missing commit.

The implementation parent for this capability is remote transport commit
`de1204ac60437fc9c8f4fccf99bdab79df471af4`, whose product capability parent is
the published Wildcard commit `0449dd7c47ae983a78fb8ef9098ce604ae3022db`.
The two intervening transport/export commits are temporary recovery machinery
and are scheduled for deletion at final Stage-14 cleanup.

## Capability

The scheduler implements a transparent finite-inventory chip policy over a
common, immutable scenario universe.

It provides:

- exact exhaustive dynamic programming below a configured state threshold;
- deterministic bounded beam search above that threshold;
- finite chip tokens with multiple copies, acquisition windows, activation
  windows, expiry, availability state, duration and one-use enforcement;
- global and mutual-exclusion concurrency limits;
- minimum gaps between chip families;
- deterministic candidate ordering and tie-breaking;
- expected-value, robust/risk-adjusted and cash-like terminal-state objectives;
- explicit `USE_NOW`, `DELAY`, `NEVER_USE`, `HOLD` and `EXPIRE_UNUSED`
  comparisons/dispositions;
- required and forbidden prefix constraints;
- prefix-sensitive memoisation so distinct candidate histories cannot share an
  invalid cached suffix;
- finite-state optimistic suffix bounds rather than exponential suffix
  enumeration;
- explored, expanded, pruned, bound-pruned and beam-pruned diagnostics;
- duplicate inventory-token rejection;
- deadline-safe opportunity lineage and fail-closed future-artifact leakage
  checks;
- nonanticipative root policy selection;
- a perfect-information diagnostic upper bound that is sealed separately and
  cannot become the executable policy;
- exact-small oracle support for independent schedule verification.

For bounded search, comparator-preservation lanes retain at least one explored
`USE_NOW`, `DELAY` and `NEVER_USE` path when legal, while the primary beam
remains constrained by the configured width.

## Defect found during adversarial validation

The first bounded-search test run exposed a real correctness defect: with a
narrow beam, pruning could eliminate the legal never-use comparator and later
make result construction fail or omit a mandatory policy comparison.

The implementation now preserves bounded comparator lanes for use-now, delay
and never-use, feeds those lanes through subsequent token groups, deduplicates
states deterministically, and still limits the main beam to the configured
width. A regression test covers beam width one and verifies all mandatory
comparator classes remain observable.

## Direct verification

### Focused scheduler suite

Command scope:

- `tests/unit/chips/test_scheduler.py`
- `tests/property/chips/test_scheduler_properties.py`

Result: `75 passed`.

The focused suite covers exact search, bounded beam behavior, deterministic
replay, token copies, windows, expiry, occupancy, concurrency, gaps, prefix
constraints, duplicate tokens, objective modes, common-scenario validation,
nonanticipativity, perfect-information separation, state-key history
sensitivity, finite suffix bounds, diagnostics, malformed inputs and the
exact-small oracle.

### Complete chip unit/property confidence

Result: `282 passed`.

This includes all completed Stage-14 chip capabilities through the scheduler.

### Coverage — branch-aware raw ratios

Raw branch-aware coverage is calculated as:

`(covered statements + covered branches) / (total statements + total branches)`.

The measurements are deliberately reported at distinct scopes:

| Scope | Statements | Branches | Raw branch-aware coverage |
|---|---:|---:|---:|
| `schedule_models.py` | `417 / 426` | `145 / 154` | `96.896552%` |
| `scheduler.py` | `431 / 438` | `149 / 154` | `97.972973%` |
| Combined scheduler modules | `848 / 864` | `294 / 308` | `97.440273%` (`1142 / 1172`) |
| Entire `dmf_pulse.chips` package | `2459 / 2537` | `841 / 924` | `95.348165%` (`3300 / 3461`) |
| `free_hit.py` direct module | `124 / 131` | `47 / 54` | `92.432432%` (`171 / 185`) |

The direct Free Hit measurement resolves the earlier evidence ambiguity: it is
above 90% on its own module. The package percentage is not presented as Free
Hit coverage.

### Static and source-integrity checks

- Ruff format check for changed files: PASS (`5 files already formatted`).
- Ruff lint for changed files: PASS.
- strict mypy for the changed production modules: PASS.
- `python -m compileall`: PASS.
- `git diff --check`: PASS before publication.

The frozen recovered Stage-14 toolchain was used because ordinary dependency
resolution attempted external PyPI access. No dependency, lock or runtime
requirement was changed for this checkpoint.

## Scope assurance

Checkpoint 14.06 changes only:

- scheduler public contracts and exports;
- finite-inventory scheduling implementation;
- scheduler unit/property tests;
- checkpoint evidence and progress.

It does not implement service, replay or CLI logic. Checkpoint 14.07 remains
untouched until this capability is published and independently visible on the
canonical remote branch.

## Status

`COMPLETE_LOCAL / PUBLICATION_PENDING` at the time this evidence was written.
The final publication SHA and local/remote equality are recorded in
`tickets/CHIP-014/PROGRESS.md` immediately after the mandatory durable
checkpoint publication.
