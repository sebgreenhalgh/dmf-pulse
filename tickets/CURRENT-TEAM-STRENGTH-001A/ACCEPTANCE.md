# Acceptance contract

All commands run from the isolated implementation checkout with Python 3.13 and frozen uv.
No live source acquisition is required. Real-corpus acceptance uses an explicit private retained
corpus; missing input is a failure, not a skip. The public repository contains synthetic fixtures
only. No raw corpus or derived per-fixture/model artifact may enter git or distributions.

Checkpoint 001A.01 commands:

```text
uv run --frozen python -m pytest tests/unit/ingestion/openfootball tests/integration/ingestion/test_openfootball_score_prior_cli.py -q
uv run --frozen python scripts/verify_team_strength_corpus.py --corpus-root review_pack/private_openfootball_corpus
uv run --frozen python -m mypy src/dmf_pulse/ingestion/openfootball/team_strength_data.py src/dmf_pulse/ingestion/openfootball/team_strength_acquisition.py src/dmf_pulse/ingestion/openfootball/team_strength_corpus.py
uv run --frozen python -m ruff format --check .
uv run --frozen python -m ruff check .
git diff --check
```

Final acceptance additionally requires mathematical/property/adversarial, artifact, adapter,
real Stage-8 and fixed reconstructed replay populations; combined new-path branch coverage
>=90%; complete inherited tests; strict mypy; frozen sync; wheel/sdist; clean installed-wheel
external-directory vertical slice; repository validator and canonical manifests; first-party
secret scan; independent review with no P0/P1/material P2; exact-SHA green CI. PostgreSQL is
inherited CI only, never a requirement of the new capability. Checkpoint evidence is not a
claim that final acceptance or human acceptance has occurred.

Checkpoint 001A.04 offline reproduction and public slice:

```text
uv run --frozen python scripts/verify_team_strength_replay.py --corpus-root review_pack/private_openfootball_corpus --private-artifact-root review_pack/private_team_strength_replay --report evidence/tickets/CURRENT-TEAM-STRENGTH-001A/reconstructed_replay.json
uv build --no-sources
uv run --frozen python scripts/verify_team_strength_wheel.py --corpus-root review_pack/private_openfootball_corpus --summary evidence/tickets/CURRENT-TEAM-STRENGTH-001A/installed_wheel_summary.json
dmf events team-strength fit-reconstructed --corpus-root PRIVATE_CORPUS --private-artifact-root PRIVATE_OUTPUT
dmf events team-strength replay --corpus-root PRIVATE_CORPUS --private-artifact-root PRIVATE_OUTPUT
```

Golden creation/update is separate and never runs in ordinary tests:

```text
uv run --frozen python scripts/update_team_strength_golden.py --replay-report evidence/tickets/CURRENT-TEAM-STRENGTH-001A/reconstructed_replay.json --confirm-fixed-policy-golden-update
```

The loader's pinned golden identity must be reviewed separately; the update script does not
change it. The public golden contains aggregate metrics and source/model identities only.
No raw results or per-fixture forecasts are packaged. The wheel script inspects both archives,
installs locked runtime dependencies offline in a fresh external environment and runs the
real public command against explicit private input. It fails if that input is unavailable.

Final local population and actual branch gate:

```text
uv run --frozen python -m coverage run --branch --data-file=review_pack/focused-final-data -m pytest tests/unit/ingestion/openfootball tests/unit/football_events tests/contract/football_events tests/unit/evaluation/test_team_strength_replay.py tests/unit/cli/test_team_strength_cli.py tests/integration/ingestion/test_openfootball_score_prior_cli.py -m "not performance" -q
uv run --frozen python -m coverage json --data-file=review_pack/focused-final-data -o review_pack/focused-final-report.json --fail-under=0
uv run --frozen python scripts/verify_team_strength_coverage.py --coverage-json review_pack/focused-final-report.json --summary evidence/tickets/CURRENT-TEAM-STRENGTH-001A/final_branch_coverage.json
uv run --frozen python -m pytest tests/unit/football_events/test_team_strength_adapter.py -m performance -q
uv run --frozen python scripts/build_team_strength_review_pack.py
```

`--fail-under=0` only permits reporting a deliberately focused population against the whole
repository source inventory; the following mandatory verifier independently enforces >=90%
actual branch coverage across every new source/model/store/adapter module with zero exclusions.
Timing is separately executed without instrumentation, with the unchanged <100ms ceiling.
The complete inherited population, PostgreSQL and overall repository coverage floor run through
the unchanged canonical eight-shard exact-SHA CI. A redundant serial local whole-repository
coverage attempt was canceled before completion and is not counted as a passing gate.
