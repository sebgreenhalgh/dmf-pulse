# A03 acceptance and execution gates

Before any provider access, run the following offline release commands and retain
UTC start/end, exit code and byte-hashed raw stdout/stderr. The socket/DNS denial
wrapper also records zero OpenLigaDB/OpenFootball/FPL/Odds requests and zero
credentials inspected. All input outcomes are synthetic; actual P01 is not scored.

```text
.venv/Scripts/python.exe review_pack/offline_pytest.py tests/unit/evaluation/test_p01_fallback_a03.py tests/unit/evaluation/test_p01_fallback_d1.py tests/unit/evaluation/test_p01_fallback_a02.py tests/unit/evaluation/test_team_strength_prospective.py tests/unit/evaluation/test_calibration.py tests/unit/evaluation/test_point_probability_metrics.py tests/unit/ingestion/openfootball tests/unit/ingestion/test_rights_and_fixtures.py --basetemp review_pack/a03-release-tests -p no:cacheprovider -q --tb=short --cov=dmf_pulse --cov-branch --cov-report=json:review_pack/a03-release-coverage.json --cov-fail-under=0
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
uv sync --all-groups --frozen
uv build --offline
.venv/Scripts/python.exe scripts/verify_p01_fallback_a02_wheel.py
.venv/Scripts/python.exe scripts/verify_team_strength_u_wheel.py
.venv/Scripts/python.exe scripts/validate_repository.py
.venv/Scripts/python.exe scripts/scan_secrets.py
git diff --check
```

The existing CI invokes the extended A02 wheel verifier, including packaged A03
authority, public execute-a03 command and zero-network precheck refusal outside
the checkout. No workflow/dependency/coverage-floor change. The partial-source
coverage report is diagnostic; normal exact-SHA CI runs all eligible tests and
the unchanged aggregate and protected branch gates.

The A03 matrix exercises all D1 projection failures through the new orchestrator,
all three fetch stages, pre-access review/CI/source/forecast boundaries, missing
or existing remote seal, malformed governance response, atomic contenders,
ambiguous creation, post-create receipt verification, single-object reuse,
alternate directories/cwd and removed local copies. Post-admission persistence
and D+2 failures must not call the scorer. After-attempt forecast authentication
must run on both paths. Exceptional failures after a score actually exists must
truthfully report that state rather than inherit D1's unscored literal.

Require fixed synthetic parent numerical equality for all 1470 metric values,
full D1/A02 parent golden parity and original OpenFootball scoring equivalence.
No generative validator may run on actual P01.

Seal a fresh 15-answer independent review with zero unresolved P0/P1/material P2
and verdict CLEAR_FOR_P01_A03_ONE_SHOT_EXECUTION. Commit that file-hash review,
publish this branch and require local SHA == remote SHA and all 20 exact-SHA CI
jobs green. Reviewer then seals an external exact-SHA binding; runtime verifies
its expected semantic SHA, committed review bytes, running package file hashes,
clean checkout/direct D1 parent, remote implementation ref and exact CI jobs.

Only then invoke the one authorized A03 execution. Atomically create and verify
the fixed remote consumption ref before constructing native HTTPS. All execution
receipts/outcomes/reports remain immutable and internal. On any acquisition or
admission failure, persist typed safe diagnostics, reauthenticate P01, stop and
do not retry/remediate/switch source/score. On complete admission, persist and
authenticate the v1 outcomes plus A03 authority binding, require existing D+2,
then use only the accepted scorer for all three frozen products.

Finally recheck every original artifact and protected policy/kernel hash, seal
the Git/CI/review/authority/execution handoff and capped review pack. External
append-only final evidence avoids a circular commit/SHA dependency. No PR,
merge, tag, OpenFootball polling, private access, tuning, promotion or activation.
