# ACCEL-001 acceptance

AB: independently varied stable metadata/types; exact/alternate/null/absent names;
blank/control/surrogate/wrong-type names; malformed group; exact-ten/orientation,
duplicate/ambiguous identities; finality/regulation/exceptional results; chronology,
D+2 and outcome/forecast binding. Preserve original A03 byte/semantic evidence.
Synthetic reconstructed forecast only, distinct actual forecast/context identities;
30 score rows and accepted scorecard internally, no legacy score persistence.
Dedicated deterministic receipt roundtrip and operational-schema rejection.
Fresh candidate review does not grant policy acceptance or A04 permission.

C: real synthetic one-/three-GW runs preserve decision hashes and legal squad,
transfers, lineup/captain/vice before deadline; exact deadline/late compute/late
render/late CLI publication fail closed; naive/invalid/reversed clocks fail typed.
Compute on either side of acquisition cutoff remains valid before the deadline.
No provider calls/retention changes. Compare timing and decisions with D2 baseline.

Run targeted tests with socket/DNS denial, inherited P01 and private/optimiser
regressions, independent oracles, strict mypy, Ruff format/lint, frozen sync, build,
installed wheel outside checkout, repository/manifests, secret scan and diff checks.
Run full canonical CI with PostgreSQL migration/integration tests, sixteen coverage
shards, combined unchanged coverage gates and post-coverage acceptance.

Literal local commands (focused test selections are recorded alongside outputs):

```
uv sync --all-groups --frozen --offline
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe evidence/tickets/DMF-PULSE-ACCEL-001/offline_pytest.py tests/unit/evaluation/test_p01_metadata_candidate.py tests/unit/evaluation/test_p01_synthetic_readiness.py tests/unit/evaluation/test_p01_fallback_a02.py tests/unit/evaluation/test_p01_fallback_d1.py tests/unit/evaluation/test_p01_fallback_a03.py tests/unit/evaluation/test_p01_fallback_d2.py -q -p no:cacheprovider --basetemp review_pack/ab-release-01
uv build --offline
.venv/Scripts/python.exe scripts/verify_accel001_wheel.py
.venv/Scripts/python.exe scripts/validate_repository.py
.venv/Scripts/python.exe scripts/scan_secrets.py
git diff --check
git diff --cached --check
```

Independent reviewers bind changed functional files, retain findings/remediations,
and clear P0/P1/material P2. Final local and remote SHA equality and exact-SHA CI
are appended outside the committed tree. Pack cap: each member <=1 MiB, total
<=20 MiB, no actual forecast/provider bodies/private recommendation persistence.
