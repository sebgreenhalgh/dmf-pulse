# 001P.01 — lineage integration

Private parent: `f39ba4ee3ea748cf60c5743e48f7f68cc6784a71`.
Public source: `6b96f5b85692fb3ec368ee261ad93a554128e017`.
Common base: `99418f3316277f4dae347d80358d5dd5a09655b2`.
Integrated eight-commit head: `508049a560c0ebc9fad7b65e8be1d9a837b7646f`.

The exact original/cherry-picked SHA pairs and 87-file public preservation proof are in
`lineage_integration.json`. Private service, availability, points, optimisation, pulse and app
files are exact git-object matches to the private parent. No substantive integration conflict
occurred. Both plan histories and wheel resource registrations were retained; conflicted current
PRC-013 manifests were regenerated against the integrated tree. Historical evidence is unchanged.

## Completed local gates

- `uv sync --frozen --offline`: PASS, existing local cache, no dependency change.
- `uv run --frozen --offline ruff check .`: PASS.
- `uv run --frozen --offline ruff format --check .`: PASS, 861 Python files at integration.
- `uv run --frozen --offline python -m mypy`: PASS, 304 source files.
- `uv build --no-sources --offline`: PASS, wheel and sdist.
- `uv run --frozen --offline python scripts/verify_team_strength_replay.py --corpus-root <retained-private-corpus> --private-artifact-root review_pack/private_team_strength_replay --report review_pack/lineage-replay.json`: PASS.
- `uv run --frozen --offline python scripts/verify_team_strength_wheel.py --corpus-root <retained-private-corpus> --summary review_pack/lineage-wheel.json`: PASS.
- `uv run --frozen --offline python scripts/verify_team_strength_shadow_lineage.py --report evidence/tickets/CURRENT-TEAM-STRENGTH-001P/lineage_integration.json`: PASS.
- Current PRC-013 and 001P manifest generation plus `validate_repository.py --ticket CURRENT-TEAM-STRENGTH-001P`: PASS, zero errors.
- `uv run --frozen --offline python scripts/scan_secrets.py`: PASS, zero findings.

Retained corpus source is the pre-existing private 001A input, not a new acquisition. Replay is
explicitly RECONSTRUCTED, holdout 2025/26, with zero network calls:

| Metric | Reproduced value |
|---|---:|
| Baseline exact-score log loss | 2.9519886029949367 |
| Original research candidate | 2.887816503690368 |
| Governed D+2 candidate | 2.887749425936601 |
| Governed candidate minus baseline | -0.0642391770583357 |

Replay golden SHA: `c32233b55d0242fa9abc74d9823235dcf8a93b16845eff80617f646166a7d1ad`.
Replay runtime: 234.788881 seconds (concurrent regression workload, not an isolated benchmark).
The external runtime-only installed wheel reproduced model SHA
`10335a94d4466f487eac92d86325d5d2dc66a8813ae872fd907f131f5c22281b` from 6080 matches. Private
corpus/model material was absent from both distributions; the packaged aggregate golden matched.

## Regression populations

Broad command:
`uv run --frozen --offline python -m pytest tests/unit/ingestion/openfootball tests/unit/football_events tests/unit/evaluation/test_team_strength_replay.py tests/unit/cli/test_team_strength_cli.py tests/unit/private_v1 -q -m "not performance" --junitxml=review_pack/lineage-regression.xml`.

Bounded checkpoint command:
`uv run --frozen --offline python -m pytest tests/unit/private_v1/test_one_command.py tests/unit/private_v1/test_a2_preparation.py tests/unit/private_v1/test_a1_allocation_injection.py tests/unit/ingestion/openfootball/test_team_strength_governance.py tests/unit/football_events/test_team_strength_adapter.py -q --junitxml=review_pack/lineage-focused.xml`.

Bounded checkpoint population: **92 passed in 529.07 seconds**. This includes the real ordinary
one-command stack, explicit three-GW one-command run, A2 preparation/provider-closure fixtures,
A1 default-service semantic equality, P0 governance and the public fixture adapter. The broader
inherited population remains running and is not yet claimed as passed here. These are checkpoint
gates, not final 001P acceptance. No score-prior seam, comparison implementation, activation, live provider action,
private live retention, PR, merge or tag has been performed at this checkpoint preparation.
