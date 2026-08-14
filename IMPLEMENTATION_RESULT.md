# DMF Pulse Stage 9 — PTS-009 integration result

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
