# R7 command evidence and resume record

## Baseline verification

- Read complete user R7 attachment and root AGENTS.md.
- `git rev-parse readiness/PRIVATE-V1-ONE-COMMAND-001N-R6-bounded-horizon-candidate-search`
  returned `5878a39448456df0d07d58823e6dfa7c8e574715`.
- `gh run view 34503653544 --json headSha,status,conclusion,jobs` confirmed
  that same SHA, completed/success and all 12 jobs successful.
- Created isolated R7 worktree/branch at that immutable SHA. Root availability
  worktree edits remain untouched.
- Read authority manifest A10/A11/B2 scope mapping; DMFP-20 OPT-001..006
  (OPT-006 remains PROVISIONAL), DMFP-12 sections 25/26/38. Accepted exact tactics,
  cohort sale proceeds, nonanticipativity and non-dominated alternatives control.
- Parent `multi_gameweek_solver.py` action enumeration resets combinations per
  state; its 17,000 guard is not cumulative. Parent `stage10_adapter.py`
  evaluate_many loops unique squads through ExactTacticalNodeKernel.optimise.

## Resume

Status: STOP / NOT ACCEPTED. Section 22 minimum speedup not met. Resume only as
unfinished exact-acceleration engineering, not acceptance/publication.

## Profile and differential commands

- `uv sync --frozen`: PASS, 40 pinned packages; dependency files unchanged.
- `uv run python scripts/profile_live_scale_exact.py --mode search --output review_pack/r7/r6-search-shape.json`:
  complete R6 fast search, 46/46/892 states, 64,288 terminal actions, 8,104 terminal
  squads. Surrogate explicitly labelled; not a physical tactical timing claim.
- `uv run python scripts/profile_live_scale_exact.py --scenarios 256 --limit 847 --no-profile --baseline-root C:/Users/sebgr/Documents/dmf-pulse/review_pack/one-command-n-r6 --output review_pack/r7/r6-kernel-family847.json`:
  R6 physical kernel baseline 339.6959693 wall / 326.328125 CPU seconds.
- `uv run python scripts/profile_live_scale_exact.py --scenarios 256 --limit 847 --no-profile --reference review_pack/r7/r6-kernel-family847.json --output review_pack/r7/r7-kernel-family847.json`:
  all 847 full results equal, 96.8327667 wall / 90.75 CPU seconds; 3.508x / 3.596x.
- `uv run python scripts/profile_live_scale_exact.py --scenarios 256 --limit 32 --output review_pack/r7/r7-final-residual-profile.json`:
  residual kernel 8.595s inclusive, bench factoring 5.845s, canonical evaluator 2.105s.
- Initial harness corrections: consistent owned-player clubs; explicit fast-path
  selection (generic default run interrupted); dataclass candidate serialization;
  JSON tuple/list normalization in full-result comparison. No semantic fields
  excluded. Only successful final runs enter benchmark.json. Initial failures are
  not reported as performance or equality passes.
- `uv run python -m pytest tests/unit/optimisation/test_stage10_batch.py -q -p no:cacheprovider`:
  4 passed; `test_stage10_r7_factoring.py`: 3 passed. Exact zero-score ties, reverse
  squad order, full distributions/hashes and original bench arithmetic checked.
- Ruff targeted checks, formatting and tactical-module mypy PASS; `git diff --check` PASS.
- `git diff --exit-code 5878a39448456df0d07d58823e6dfa7c8e574715 -- src/dmf_pulse/private_v1/horizon_candidates.py src/dmf_pulse/private_v1/rolling.py src/dmf_pulse/private_v1/service.py src/dmf_pulse/optimisation/multi_gameweek_solver.py`:
  PASS, protected R6 semantics byte-identical.

No R7 exact-SHA CI or complete acceptance claimed. No live credentials read or
requested. No new cumulative STANDARD guards installed to conceal residual work.

## Final checkpoint gates

- Combined `test_stage10_batch.py`, `test_stage10_r7_factoring.py`,
  `test_stage11_exact_acceleration.py`, `test_future_transfer_scope.py`:
  **67 passed in 111.18s**.
- `uv run python -m ruff check .`: PASS.
- `uv run python -m ruff format --check .`: 777 files formatted, PASS.
- `uv run python -m mypy src`: 285 source files, PASS.
- Canonical PRC-013 and R7 repository manifests generated, 1,354 files each.
- Manifest integration: 4 passed in 2.38s; repository validator: zero errors.
- First-party secret scan: zero findings; `git diff --check`: PASS.
- Final checkpoint remains local/unpublished because the performance stop condition
  was reached; there is no R7 exact-SHA CI result and no accepted final release SHA.
