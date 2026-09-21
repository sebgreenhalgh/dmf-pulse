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
