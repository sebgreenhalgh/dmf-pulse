# DMF Pulse Stage 9 — PTS-009 integration result

# RUL-002R3 PLAYER_POINTS static-review remediation

## Identity

- Starting branch / reviewed HEAD: `stage/R2/FPL-2026-27-rules` / `7041e04bda669f6e478aa69f1d8d2a7c0ff7ee7c`.
- Accepted base and merge-base: `9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272`.
- Reconstructed lineage before this remediation: accepted Stage 9 `b8107aa413bc8483d6506288738a96b1f3fbd7e4`, then replayed R2 implementation `3fe71f9` and prior evidence `0bfaffb`.
- The final commit identity is reported by the completion response after the required evidence-only commit; recording a commit's own object ID in its content would be self-referential.

## Finding disposition

| Finding | Disposition | Implemented evidence |
| --- | --- | --- |
| P1-1 manager-state leakage | FIXED | `src/dmf_pulse/rules/capabilities.py`, target `capabilities.yaml`, and `test_player_points_dependency_closure_excludes_manager_state` remove `/rules/positions` from PLAYER_POINTS and recursively reject manager leaves. |
| P1-2 save/BPS contract | FIXED | `src/dmf_pulse/rules/bps.py`, `models.py`, and Stage-9 allocation/adapter retain additive `big_chance_saves`, total-save semantics, subset checks at schema v1.1 scoring, and non-GK save participation. `test_2026_27_save_contract.py` is the exact matrix. |
| P1-3 executable assists | FIXED | `src/dmf_pulse/rules/assists.py`, typed `AssistDecisionContext`, target `assists.yaml`, and `AcceptedRulesAdapter` execute compiled policy before an assist is counted. `test_versioned_assist_classification.py` runs cases A-R through the Stage-9 boundary. |
| P2-1 interpretation evidence | FIXED | Structured approval-state consistency in `authoring.py` and `capabilities.py`; the target verification note correctly identifies `INT-FPL-2026-BONUS-TIES-001` as a separately human-approved PLAYER_POINTS interpretation. |
| P2-2 accepted-base reconstruction | FIXED | The reviewed R2 work was replayed onto accepted base `9d7c360...`; local `origin/main` matched that accepted commit. No network access was used, as required by the remediation pack. |

## Capability matrix

| Capability | Source-backed | Ready | Production eligible | Blockers |
| --- | ---: | ---: | ---: | --- |
| PLAYER_POINTS | true | true | true | `[]` |
| GW1_INITIAL_SQUAD | false | false | false | unresolved squad, lineup, initial/current price, and GW1 deadline rules; bonus interpretation is out of scope |
| TRANSFER_STATE | false | false | false | GW1 blockers plus transfers and selling-price rules; bonus interpretation is out of scope |
| CHIP_STATE | false | false | false | transfer-state blockers plus chips and automatic substitutions; bonus interpretation is out of scope |
| FULL_SEASON | false | false | false | manager-state blockers including prices, deadlines, special events, transfers, chips, and bonus interpretation out of scope |

PLAYER_POINTS dependency paths are exactly `/rules/scoring`, `/rules/assists`, and `/rules/bonus`. The recursive leaf scan found no manager-state path or `squad_quota`, `lineup_min`, `lineup_max`, or bench leaf.

## Rule identities and deterministic artifacts

- Schema-v1.0 reference hash: `12271ab0b32a461baa3778f2e914f45744ccf9d5302c37c4a5f2ffb89e0c1139`.
- Schema-v1.0 synthetic hash: `98e8614d9971ec2b1e45a357e89f79172bbc5dd4dc87044c3c131b3de6b0aab8`.
- Schema-v1.1 ruleset hash: `afa1364d7d7adfc632d73782f46707bb4f92d3961ca1946d4c8cab0496c2f8ff` -> `c9fee6287bcb12170aa2f046d486dd812cfa0404efe214344e39f5aeb739cccf`.
- PLAYER_POINTS capability hash: `2f0fcaee9e5670dcc83d7704de0d220eacbc7f532d862504f530fe57795267b4` -> `68898c5c9c4f2e2b14001cc1a1625a169eb9858fe20b7e31a45c359077bdec51`.
- Approved interpretation hash: unchanged, `dfe10d4dabf8183c10f4a61d3bd2361bd54ee78d24c96ee9d38da42becfbaa49`.
- Rules artifact SHA-256: `f13dd31faa8013df59688adb63d49ab4b59a763246ec6b1ec88af8a0ed5c3574`.
- PLAYER_POINTS artifact SHA-256: `380a8be997bc286033bc78dbfbae2d628818ee3bf5b7cb43aac87667e51b42fb`.
- Two independent compilations produced byte-identical rules and capability artifacts.

The global target remains `CAPTURED_UNVERIFIED` and `production_eligible=false`; no capability other than PLAYER_POINTS is promoted and the global ruleset is not ACTIVE.

## Exact scenario matrices

Assist cases A-R all pass through `Stage-9 GoalEvent -> AcceptedRulesAdapter -> rules classifier -> exact assist component`: direct pass; one/two defensive touches; defensive pass; outside-box intent; rebound/save; further touch; own rebound; own-goal actions; penalty/free-kick foul winner and self-taker; pass/touch handball; on-target/off-target deflected-shot handball; and corner/throw-in exclusion.

The save/BPS matrix passes: outside, inside, big-chance, inside big-chance, neutral/unlocated, saved penalty, three-save FPL point grouping, non-GK save participation, contradictory subset rejection, and Stage-9 adapter preservation. The saved-penalty BPS total is 17, comprising appearance 6 plus save components 7 + 2 + 1 + 1.

## Executed evidence

```text
uv run pytest tests/unit/rules/test_schema_v11_capabilities.py tests/unit/rules/test_2026_27_save_contract.py tests/unit/fpl_points/test_versioned_assist_classification.py tests/unit/rules/test_scoring_edges.py tests/property/rules/test_rules_properties.py tests/contract/fpl_points tests/golden/fpl_points -q
96 passed

uv run pytest tests/unit/rules/test_schema_v11_capabilities.py tests/unit/rules/test_yaml_and_compiler.py tests/unit/rules/test_authoring_schema.py tests/unit/rules/test_2026_27_verification_gate.py tests/unit/rules/test_2026_27_save_contract.py tests/unit/fpl_points/test_versioned_assist_classification.py -q
110 passed

uv run pytest tests/unit/rules tests/property/rules tests/golden/rules tests/contract/fpl tests/unit/fpl_points tests/contract/fpl_points tests/integration/fpl_points tests/golden/fpl_points tests/property/fpl_points -q
249 passed

uv run pytest -q --ignore=tests/performance
1570 passed, 1 skipped; 205 PostgreSQL-dependent errors because DMF_TEST_DATABASE_URL was intentionally absent; two expected pre-evidence failures (wheel requires that same database URL and stale current manifest).
```

No network, dependency, migration, Stage-7, or Stage-8 changes were made. The remaining limitation is intentionally unresolved manager-state/full-season functionality; it does not qualify PLAYER_POINTS as global activation.

# RUL-002R4 Stage-9 assist-allocation remediation

The R4 implementation preserves the R3 rules artifacts and approvals while closing the
remaining generator-path gap: `allocation.py` samples candidate/goal-mechanism facts,
then invokes `AcceptedRulesAdapter.classify_generated_assist`, which delegates to the
compiled `dmf_pulse.rules.assists.classify_assist` policy. Only a
`DEFINITE_ASSIST` increments the candidate's `eligible_assists`; every evaluated
target-v1.1 candidate records its typed context and result on `GoalEvent`.

- PENALTY and DIRECT_FREE_KICK emit `DIRECT_*` / `FOUL_WON` contexts. The compiled
  policy awards a different foul winner and rejects a self-taking candidate.
- OPPONENT_OWN_GOAL emits `OWN_GOAL` / `FORCED_OWN_GOAL_ACTION`, preserving the
  conceding-side own-goal player and allowing a scoring-side forcing-action assist.
- Target-v1.1 rejects unresolved `AMBIGUOUS_ASSIST`, including no-context bypasses.
  Legacy schema-v1.0 allocation preserves its existing compatible ambiguity path.
- `PLAYER_POINTS` remains independently eligible; the global ruleset remains
  `CAPTURED_UNVERIFIED`, not production eligible, and not ACTIVE. Ruleset hash,
  capability hash, and approved interpretation hash are unchanged from R3.

The ordinary TEMP-EVT-002 save generator still samples only FPL-position GKs. The
scoring/event contract permits temporary non-GK goalkeeping, but generating that role
requires future role-state modelling and is documented as nonblocking rather than
misrepresented as fixed.

R4 focused verification: 63 allocation/adapter/service tests, 49 rules/capability
tests, and 109 Stage-9 affected tests passed. `ruff format --check .`, `ruff check .`,
`mypy src/dmf_pulse`, deterministic PLAYER_POINTS recompilation, and the secret scan
passed. No rules-data artifact changed: target hash remains
`c9fee6287bcb12170aa2f046d486dd812cfa0404efe214344e39f5aeb739cccf`, capability
hash remains `68898c5c9c4f2e2b14001cc1a1625a169eb9858fe20b7e31a45c359077bdec51`,
and the approved interpretation hash remains
`dfe10d4dabf8183c10f4a61d3bd2361bd54ee78d24c96ee9d38da42becfbaa49`.

## Status

**Implementation and clean-checkout integration complete; independent review and
human acceptance remain separate.** Production 2026/27 output is not ready because
the target ruleset is not verified, approved, production eligible, or ACTIVE.

## Source and Git basis

- Candidate ZIP SHA-256:
  `d01bd3868dcecf5f5165680ec2c0a4a08a0fa18dedc0833f1223792cf72fe002`
- ZIP entries independently enumerated: 58
- Branch: `stage/A9/PTS-009-fpl-points-simulation`
- Accepted parent: `9d7c360ab6a4cc7bfc6d6f41e44be6b47512b272`
- Final GCS-008 implementation lineage:
  `69b665315ab20b8ac13a38fafed7b5c64ff7e7ce`

The initial branch, parent, worktree, and origin branch matched the request before
application. `src/dmf_pulse/cli/app.py` was manually reconciled so all accepted
commands remain registered.

## Material integration work

- Replaced provisional Stage 8 aliases with the final accepted
  `JointScoreDistribution`, exact 12-place matrix, cutoff/as-of, semantic hash, and
  `Stage7MinutesContext` contracts.
- Bound actual Stage 7 `MinutesPredictionResult` / `TeamMinutesProjection` and every
  accepted player projection hash; no Stage 7/8 mathematics was copied.
- Removed NumPy and implemented versioned SHA-256-derived standard-library named RNG
  streams plus exact 10^12 matrix sampling. Dependencies and `uv.lock` are unchanged.
- Replaced the candidate's duplicate reference arithmetic with an actual compiled
  reference artifact and `AcceptedRulesAdapter`.
- Strengthened goal/assist/mechanism/team/player reconciliation and joint BPS handling.
- Added byte-identical packaged model resources and deterministic resource generation.
- Hardened artifact, coverage, scope, resource, and installed-wheel verification with
  fail-closed and mutation tests.
- Corrected acceptance ordering so migration precedes database tests and wall-clock
  performance is measured outside coverage instrumentation.

## Executed gates

Toolchain: Python 3.13.9, pytest 9.1.1, coverage.py 7.15.2, Ruff 0.15.22,
mypy 1.20.2, uv frozen environment, PostgreSQL 18.4.

### Static, build, and dependency gates

```text
uv sync --all-groups --frozen                         PASS
python -m compileall -q src tests scripts            PASS
ruff format --check .                                PASS (379 files)
ruff check .                                         PASS
mypy src/dmf_pulse                                   PASS (140 source files)
```

No dependency file changed.

### Stage 9 tests and coverage

```text
pytest [Stage-9 unit/property/contract/golden/integration/assurance with branch coverage]
80 passed in 38.84s
pytest -q tests/performance/fpl_points
1 passed in 12.60s
```

Collection by layer: 40 unit, 6 Hypothesis property, 10 contract, 4 golden,
7 integration, 13 assurance mutation, and 1 performance test.

Stage 9 package coverage:

- statements: 1,650 / 1,786 = 92.38521836506159%
- branches: 428 / 542 = 78.96678966789668%
- combined: 89.26116838487972%
- required gate: at least 85% statements and 70% branches, PASS

### Inherited compatibility

```text
accepted Stage 2 rules                  75 passed
accepted Stage 7 availability          168 passed
final Stage 8 football-events          168 passed
```

Total directly relevant inherited coverage: 411 passed.

### Final repository regression

The final product/test/resource tree ran once with the separately passed performance
test excluded from coverage instrumentation:

```text
pytest -q --ignore=tests/performance --cov=dmf_pulse --cov-branch \
  --cov-report=json:evidence/stages/09/repository_coverage.json
1694 passed in 640.05s
```

- statements: 16,406 / 17,588 = 93.27950875596999%
- branches: 4,804 / 5,462 = 87.95313072134749%
- coverage.py combined: 92.0173535791757%
- repository 90% combined gate: PASS
- skipped/xfail: 0 reported

Earlier diagnostic runs are not acceptance evidence: the first reached an unmigrated
database, and the second identified a deliberately stale repository snapshot plus the
invalidity of enforcing a real-time performance budget under branch coverage. Both
gate-order defects were corrected before the final green run.

### Mathematical and assurance gates

The real Hypothesis suite and deterministic contract/golden tests verify goal
conservation, on-pitch eligibility, scorer/assist separation, exact Stage 8 scorelines,
integer components/BPS/totals, component sums, negative support, normalized weights
and PMFs, monotone quantiles/thresholds, joint-matrix dimensions/mapping, seed and
partition invariance, blank Gameweeks, exact multi-fixture sums, production rules
blocking, complete BPS universes, and joint bonus ranking.

All 13 assurance mutation tests passed. Independent artifact assurance rejects
semantic/matrix/ruleset/player/upstream/component tampering and requires accepted-rules
recomputation. Scope, resource, and coverage assurance each returned PASS.

### Database

- Alembic heads: one, `20260807_0006`
- Migration matrix: 5/5 transitions PASS from baseline `20260803_0005` to head
- Metadata drift and preservation: PASS
- PostgreSQL integration: 110 passed, 117 deselected in 198.90s
- PostgreSQL: 18.4; 71 tables; 12 views
- Schema SHA-256:
  `7466ab96b6ffa19236cfa197e480c7bef86d57c4bb8f486d55fcfdec39bf57cc`
- Disposable container/network/volume removed after the gate

PTS-009 adds no migration.

### CLI, artifacts, and wheel

Repository TEST CLI `simulate-fixture`, `validate`, and `mc-diagnostics` passed; the
independent artifact checker passed. The deterministic 32-scenario result has semantic
SHA-256 `41082efbf1d2d795681f4e37ca3b7a42415ea8c03ab3d70cd3d3f5863e5f3b27`
and canonical artifact SHA-256
`ea264381d307af719f4a58591396296ff425560b4b0000f15f8778310f768111`.

The built wheel `dmf_pulse-0.2.0-py3-none-any.whl` has SHA-256
`07bf255008dcb840816e6557de0c9943e6d6eac3483089656b5c9f5bc8059a38`.
The isolated verifier checked all 176 RECORD members, installed outside the checkout
without `PYTHONPATH`, imported Stage 9 from temporary `site-packages`, exercised the
TEST CLI, and confirmed PRODUCTION exits 4 with `RULESET_NOT_ACTIVE`.

Repository validation and the secret scan pass after mechanically refreshing the
714-file current repository snapshot. Independent Stage 9 review, merge, and human
acceptance were not performed.

## Frozen Stage 9 identities

- fixture manifest SHA-256:
  `457698f877ad1dc79bcbe1c3f8e707b664f1bab27df61c0dd93008973d3b9347`
- request SHA-256:
  `fb8ed57b63087ae3563fdf37ca4e8a77e71a8af333a4668e9a960eb0eace40af`
- golden cases SHA-256:
  `9bf3657baac70e768747a592b1da2ef2fc24aa774857f43deae2ae8c0df90c19`
- Stage 7 context semantic SHA-256:
  `d5af65b3be0bc6ca02759953b2599cf8a98c2ad198c83e4aa230c726a89d20c2`
- Stage 8 result SHA-256:
  `31d41317c0cf06002edd8e8fb47c4702706661f2227304182e3c4b8995e06b7e`
- reference rules embedded hash:
  `12271ab0b32a461baa3778f2e914f45744ccf9d5302c37c4a5f2ffb89e0c1139`
- event-allocation config SHA-256:
  `4d5aba182310ce70ed2bf6f0abfed4a4b1fc9ef9ca8f3abf7363ec21f0e8c85e`
- Monte Carlo config SHA-256:
  `14107f715769abb2d1bfc2937753c820a7d3eb02c23ae8e8a76350eaa88c0454`

## Remaining modeling limits

TEMP-EVT-002 and TEMP-PTS-001 require production calibration. Multiple-fixture
Gameweeks omit sequential readiness transitions. Advanced prop reconciliation, full
event/BPS residual modeling, and every Stage 10+ manager-state/optimisation feature
remain deliberately excluded.
