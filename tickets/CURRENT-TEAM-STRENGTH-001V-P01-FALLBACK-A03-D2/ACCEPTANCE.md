# D2 acceptance

1. Offline synthetic matrix: each of five metadata fields independently correct,
missing, wrong type and wrong value; group object missing/wrong type; strict
integer bool/float/string refusal; string bytes/int/list/null refusal; alternate
descriptive name remains refused; stable mismatch precedence; correct metadata
reaches unfinished/missing-final/valid finished-regulation checks. Reordering
retains exact outcomes; ambiguous mapping fails closed.
2. Diagnostic schema is closed, immutable and value-free; stage/reason bind to
field. Original A03 diagnostic byte/semantic hashes and serialized payload match.
3. Full A02/D1/A03 regressions, unchanged full synthetic metric/outcome/score/report
semantics; both consumed-attempt protections remain. No new authority config,
CLI or transport. Socket/DNS denial records zero attempted access in tests.
4. Authenticate historical artifact inventory and protected scorer/context/rights,
workflow/dependency files; P01 both hashes exactly match before and after.
5. Fresh independent reviewer answers all twelve user questions and clears all
P0/P1 and material P2 findings; review binds all changed functional files.
6. Literal release commands (module entrypoints avoid Windows executable policy):

```
uv sync --all-groups --frozen
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe review_pack/offline_pytest.py tests/unit/evaluation/test_p01_fallback_d2.py tests/unit/evaluation/test_p01_fallback_d1.py tests/unit/evaluation/test_p01_fallback_a03.py tests/unit/evaluation/test_p01_fallback_a02.py tests/unit/evaluation/test_team_strength_prospective.py tests/unit/evaluation/test_calibration.py tests/unit/evaluation/test_point_probability_metrics.py tests/unit/ingestion/openfootball tests/unit/ingestion/test_rights_and_fixtures.py --basetemp review_pack/d2-release-tests -p no:cacheprovider -q --tb=short --cov=dmf_pulse --cov-branch --cov-report=json:review_pack/d2-release-coverage.json --cov-fail-under=0
uv build --offline
.venv/Scripts/python.exe scripts/verify_p01_fallback_a02_wheel.py
.venv/Scripts/python.exe scripts/verify_team_strength_u_wheel.py
.venv/Scripts/python.exe scripts/validate_repository.py
.venv/Scripts/python.exe scripts/scan_secrets.py
git diff --check
git diff --cached --check
```

7. Current repository manifests validate; raw command bytes/hashes authenticate.
Capped pack: each member <=1 MiB, total <=20 MiB; include hashes for excluded
large artifacts without copying P01/provider data.
8. Publish D2 branch only; local SHA equals remote SHA; exact-SHA mandatory full
CI all twenty jobs successful with full test plan and combined coverage gate.
Final publication evidence is append-only outside the committed tree to avoid
self-referential commit/CI hash. No PR, merge or tag.
