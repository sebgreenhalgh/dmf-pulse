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

## Resume-only continuation (new user instruction)

- Verified exact branch, clean worktree and HEAD `65f344dc0661179dbd3963ae2fc8a8ad3aad2ff6`.
  Resumed in place, without reset/recreation or intermediate push. Historical STOP
  above is superseded by the user's explicit resume instruction, not acceptance.
- Terminal sale-price fingerprint RED: missing imports. Implemented final-node-only
  eligibility, separate decision fingerprint and full-history replay. Corrected
  synthetic terminal advancement through legal hold transitions and closed-spell
  catalog metadata; no test assertion weakened.
- Layer batching RED: generic candidates equal but 37 terminal batches instead of one.
  Forward exact reachability plus backwards node batches/frontiers implemented.
- Terminal/layer suite: 17 passed in 157.21s, including all complete generic candidate
  fields for root/future/budget/club cases and 50/51 purchase-cohort variants.
- Packed bench integers preserve all orders with explicit signed absolute bounds;
  node-local canonical scenario interpretation/resolver reuse preserves verification.
  Existing tactical/factoring suite: 7 passed in 16.26s.
- 847x256 packed-only full differential: 67.2579756 wall / 64.578125 CPU, 5.0506x;
  with canonical reuse: 60.8718921 wall / 57.96875 CPU, 5.5805x. All 847 outputs equal.
  These are exploratory single samples, NOT final repeated performance acceptance.
- Frozen structural request, complete candidates and squads-by-node compare exactly
  to R6. Initial layered variant used 1 batch/node but replayed transitions twice,
  costing 82.14s vs 44.18s surrogate baseline. Keep validated transitions under a
  cumulative envelope and consume them backward to remove that repeated work.
- Added pre-tactical cumulative combination discovery guard using the inherited
  max_policy_candidates envelope (250,000 STANDARD), plus unchanged state cap.
  Measured 67,062-combination structural shape fits. Added fail-before-batch tests.
- Added non-semantic discovery/solve/tactical CPU+wall counters and logical/factored
  kernel progress disclosures. Candidate, objective, FT and scenario inputs unchanged.
- Current status: repeated physical timing, new guard/canonical tests, actual physical
  Stage-10/11 and full private-stack frozen replay, full regression/coverage/local
  acceptance and exact-SHA CI still pending. No final acceptance or push yet.

### Resume validation checkpoint (not publication acceptance)

- Corrected the cumulative envelope to count retained **legal actions**, not raw
  rejected combinations. Existing per-state combination/state limits remain;
  the inherited 250,000 STANDARD policy envelope bounds cumulative retained
  transitions before tactical evaluation. A hostile unaffordable-input test
  proves raw combinations cannot incorrectly consume that legal-work allowance.
- Targeted R7/R2/R4 and new terminal/layer/guard/canonical matrix: **93 passed in
  399.74s**. All three nonzero terminal coefficients and paid continuation fallback
  are covered. Full Ruff/format: PASS (782 files); mypy: PASS (285 source files).
- Real Stage-10/11 frozen replay: exact equality of the entire sealed request,
  complete candidates and final result, with no excluded result/hash fields.
  Both evaluate 395 unique node/squads with 256 joint scenarios; R6 uses 48 physical
  batches, R7 uses 3. Correctness runs overlapped other validation and are not
  primary benchmark samples (263.60s / 58.13s wall respectively).
- Native full-stack builds cannot consume identical upstream market artifacts:
  existing market provenance hashes the **whole installed package**. R6 artifacts
  correctly fail R7 exact-source verification; no production check was changed.
  The synthetic replay explicitly freezes only market build identity in both
  processes while recording actual package identities separately. All actual
  upstream calculations and source verification still execute. With this labelled
  synthetic provenance input, execution/request/projections/full decision/full
  optimiser result/one-GW result match exactly, including all hashes. This is
  algorithm-semantic evidence, not a claim of native cross-build provenance identity.
- Repeated isolated tactical outputs all have semantic SHA256
  `26258b0493a9dfb584d061477e80a567caf0a6d9d61912f074fa1c498843d30d`.
  R6 samples 1/2 loaded current shared helpers and are excluded. Valid R6 samples
  are repeated-r6-3, isolated-r6-4, isolated-r6-5; R7 samples 1/2/3 are valid.
  R6 timing variability must be disclosed, not presented as an unqualified gain.
- Broad fresh branch coverage, final structural replay, build/installed wheel and
  remaining publication gates are running/pending. Nothing has been pushed.
