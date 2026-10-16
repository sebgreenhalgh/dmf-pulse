# D1 acceptance

All provider transports/connections are fake. The focused suite runs under a
socket/DNS denial wrapper and records zero provider calls. Real P01 is never
loaded into a scoring/model-building path. Historical A02 cause stays unknown;
all49 original P01/A01/A02 artifact bytes are checked before/after D1.

| Gate | Proof |
| --- | --- |
| Historical preservation | Authenticated immutable consumption record plus original49-file inventory; no elapsed-time inference or fabricated historical receipt |
| Closed classification | Finite15-stage and31-reason enums; typed boundaries and unknown-error translation; no exception-message parsing |
| Transport | Fake non200/type/length/stream/deadline/socket timeout/connection/truncation; finite route/type classes, bounded observed bytes and explicit digest completeness |
| JSON/metadata | Duplicate key/malformed JSON; missing/duplicate global and league candidates; link disagreement |
| Projection | Wrong response shape,9/11rows, unfinished, absent/duplicate/type-mismatched regulation result, exceptional descriptors, missing/invalid/naive played timestamps, invalid score/ID integers |
| Admission | Missing/ambiguous oriented mapping, ambiguous provider-club identity, schema failure, exact counts and no labels/IDs/names in stopped diagnostics |
| Post-admission | Persistence failure and real D+2 boundary after outcome persistence; no partial scoring |
| Unknown failures | Inject RuntimeError at every nonterminal stage; no arbitrary exception text/cause/trace in safe output |
| Authority | Packaged consumed-context tombstone independent of root/marker existence; default transport denied and operational A02 denied independently of injected transport; HTTP tests use fake factories under socket denial; no force/reset flags or A03 authority |
| Diagnostic storage | Strict extra-forbid schema, hash tamper rejection, rights before storage, post-mkdir confinement, fsync plus atomic exclusive publication, safe secondary persistence failure |
| Success parity | Full parent outcome/score/scorecard SHA equality and all1470metric values, from fixed captured syntheticinput; original OpenFootball path exact equality retained |
| Installed package | Existing clean-wheel verifier extended with packaged consumption, no-request authority refusal and stopped-record replay outside source tree |
| Review | Fresh15-question independent assessment, rights conclusion and CLEAR_FOR_P01_A03_REAUTHORIZATION_DECISION; no execution authorization |
| Release | Commands below and all mandatory exact-SHA CI jobs |

Literal focused command (Python wrapper invokes pytest; partial-source coverage is
diagnostic only, while unchanged full exact-SHA CI enforces the repository floor):

```text
.venv/Scripts/python.exe review_pack/offline_pytest.py tests/unit/evaluation/test_p01_fallback_d1.py tests/unit/evaluation/test_p01_fallback_a02.py tests/unit/evaluation/test_team_strength_prospective.py tests/unit/evaluation/test_calibration.py tests/unit/evaluation/test_point_probability_metrics.py tests/unit/ingestion/openfootball tests/unit/ingestion/test_rights_and_fixtures.py --basetemp review_pack/d1-release-tests -p no:cacheprovider -q --tb=short --cov=dmf_pulse --cov-branch --cov-report=json:review_pack/d1-release-coverage.json --cov-fail-under=0
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

Windows AppControl requires installed Ruff/mypy through Python -m. Every release
command has exact UTC times/exit status and byte-hashed raw stdout/stderr in
evidence/tickets/CURRENT-TEAM-STRENGTH-001V-P01-FALLBACK-A02-D1/COMMAND-*.json/log.
The existing manifest API's40-character identifier cap remains unchanged; only
manifest metadata uses alias CURRENT-TEAM-STRENGTH-001V-P01-D1, with its generated
manifest retained inside this full official ticket evidence directory. Refresh
the existing validator-selected PRC-013 current manifest too. No dependency or
workflow-gate changes. Commit/push this branch only; verify local/remote equality
and exact-SHA CI. No PR/merge/tag/provider call/real P01 score/activation.
