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

### Final-code local gates completed during broad regression run

- Full structural replay: request, every complete candidate and every node/squad
  entry exactly equal R6. 67,062 legal actions, 8,997 node/squads, 3 node batches.
  1,283s wall vs 68.75s CPU includes suspension; excluded from performance claims.
- `uv sync --frozen`: PASS, 40 packages. `uv build --no-build-isolation`: PASS,
  0.2.0 wheel/sdist. `uv run python scripts/verify_current_score_prior_wheel.py`:
  PASS, offline/external environment and native rights/hash defenses intact.
- `uv run python scripts/verify_r7_private_wheel.py --synthetic-execution review_pack/r7/native-wheel-input/frozen-execution.json`:
  PASS, installed `dmf pulse --help` and full native-build private three-GW service;
  decision SHA256 `06a33e5e8266d5808f3358e5a23c31c1db848a469f6173fc8710ce91f135000c`.
  The harness streams only repository-owned synthetic execution through stdin;
  the initial command-line payload correctly encountered Windows error 206.
- Full Ruff/format: PASS, 785 files; mypy: PASS, 285 source files. Specs validation:
  PASS, 94 decisions/22 documents/19 scopes. Secret scan: zero findings. Read-only
  repository validator: zero errors. `git diff --check`: PASS.
- Canonical PRC-013 and R7 manifest generation: PASS; manifest integration: 4 passed.
  Manifests must be regenerated again after final evidence/test edits.
- CI collection using the full checkpoint SHA: PASS, 4,418 eligible tests at that
  checkpoint. Additional defense tests require a final recollection. An abbreviated
  SHA was rejected by the collector as designed; the command was corrected.
- Canonical review builder: `REVIEW_TICKET_UNSUPPORTED`. No contract/authority
  bypass. Prepare a separately labelled supplementary capped archive only.
- Fresh final focused coverage: 27 passed (8 generic variants deliberately excluded
  from this focused run, but included in the targeted/broad matrices). Separate real
  private-service/counter coverage: 2 passed, plus 1 individual-CPU-counter test passed.
  Combined completed runs: **344/344 = 100%** changed executable lines plus originating
  branch arcs, including smallest statement origins for multiline edits.
  Exploratory interrupted coverage is excluded from this combined data.
  Coverage summary SHA256 `cbbf5bc511b7c4a1ff37672502e4e3564ef18b33b881fca1c4595cdbe02a5975`;
  full JSON SHA256 `a6ad66f719e1ddc94de51b77d75c3a113ada9848d4a2ab3360fac874dc652538`.
  This is not the unchanged whole-repository CI threshold.
- Exact source scope audit: V3 screen, rolling input models, one-command assembly,
  ingestion, Stage-7/8/9 modelling, configuration, dependencies and CI files remain
  byte-identical to R6. Production source hashes and all frozen comparison artifact
  hashes are now included in `repeated_benchmark.json`.
- Broad regression and independent review remain pending. No push or live run.

### Whole-public-solve correction and current production snapshot

- The first broad coverage run completed: **585 passed in 4243.12s**. During final
  audit, found that the public solver's separate no-transfer baseline had its own
  enumerator budget and was absent from the main profile. This was a governance
  gap, not a tactical/objective mismatch. Preserve the completed run as checkpoint
  evidence; rerun the entire matrix on the correction below.
- Added one physical `Stage11WorkBudget` per public solve, shared by the full
  frontier and baseline, with shared profile accounting. It cannot relax either
  sealed policy cap. Plan construction, root/future actions, candidate screening,
  FT rules and mathematical selection remain unchanged. A baseline budget failure
  follows the existing fail-closed baseline-error contract and emits no recommendation.
- Shared legal/state boundary and complete generic tests: 4 passed; larger supplied
  budget versus tighter sealed-policy tests: 2 passed. Corrected fresh coverage:
  34 passed, plus 2 completed appended defense cases. **367/367 = 100%** across all
  six changed production files. Summary SHA256
  `91c7eaa1caab9bf79884c2575d9299d66b518569d57bf23a1537bd831d66b3af`;
  full JSON SHA256 `fe11650eb6150f09dd9c79d6645e942d622a9c23e087e83fced565cf75e840f9`.
- `profile_live_scale_exact.py --mode search --public-search --no-profile`:
  complete, **130,317 cumulative legal/actions combinations**, 1,788 solved states
  including both roots, 8,997 unique node/squads. Existing 250,000 legal-action and
  25,000 non-root state envelopes admit the complete measured shape. This is a
  labelled tactical surrogate; its timings are not the primary tactical benchmark.
- Corrected real Stage-10/11 replay and fixed-provenance full private replay again
  match every selected semantic field, with no nested hash/decision exclusions.
  `repeated_benchmark.json` binds their refreshed artifacts and six source hashes.
  Tactical source bytes/primary timing samples are unchanged by this budget fix.
- Corrected frozen sync, build and both clean external wheel checks: PASS.
  Native full private wheel decision SHA256:
  `c60d65afc0138b6947dd0b0256924f954c4365f573012682f99c5979cb8b5554`.
  Input: `review_pack/r7/native-budget-wheel-input/frozen-execution.json`.
- Corrected full regression command (without coverage overhead; fresh changed-code
  branch coverage is measured separately above) is running:
  `uv run python -m pytest tests/unit/private_v1 tests/unit/optimisation tests/property/optimisation tests/contract/optimisation tests/golden/optimisation tests/unit/ingestion/test_fpl_entry_duplicate_resolution.py tests/unit/ingestion/test_one_command_assembly.py -q --tb=short -p no:cacheprovider --basetemp=review_pack/r7/final-budget-regressions`.
- Independent review, final manifest/evidence reconciliation and publication remain
  pending. Read-only remote check confirms no R7 branch has been published.

### Automated local gates complete; independent review remains a publication gate

- Corrected full command above: **592 passed in 1130.93s**. The two subsequently
  added oversized-shared-budget defense cases separately passed; all production
  bytes stayed fixed throughout these final runs.
- Corrected final CI collection: **4,427 eligible tests**, node-ID set SHA256
  `de31324c53047545cd0b7666ecad252fe9a196d46255d967c2932df249e7e605`.
- Final Ruff/format, strict mypy, secret scan and specification validation: PASS.
  Canonical manifests/repository validation are reconciled again when sealing this
  local checkpoint; supplementary archive binds exact committed source bytes.
- Independent review was requested through a nonblocking user question. No
  permission for another agent and no independent review result have been received.
  Do not infer permission or call author checks an independent review. Do not push
  before this repository-required acceptance gate is cleared.
- R7 remains **NOT PUSHED**; exact-SHA R7 CI, PR, merge, tag, activation and live retry
  have not been performed. Parent CI is not evidence for this local candidate.
