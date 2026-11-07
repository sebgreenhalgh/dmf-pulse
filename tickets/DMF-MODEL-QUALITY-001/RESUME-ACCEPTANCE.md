# Continuation acceptance

The original ACCEPTANCE.md remains historical baseline evidence. All unchanged
coverage, installed-wheel, PostgreSQL, performance and release gates remain.
Continuation captures go under `evidence/tickets/DMF-MODEL-QUALITY-001/resume/`;
never overwrite a sealed baseline receipt to make it describe later source.

Literal local commands (Python3.13, frozen offline environment):

```
uv sync --all-groups --frozen
uv run --frozen ruff format --check .
uv run --frozen ruff check .
uv run --frozen mypy src/dmf_pulse
uv run --frozen python scripts/dev_checks.py integration --target tests/integration/operation/test_analysis_fixture_parity.py --target tests/unit/scripts --target tests/unit/operation/test_analysis_fixture_integrity.py
uv run --frozen python scripts/dev_checks.py focused --target tests/unit/operation/test_analysis_quality.py --target tests/unit/operation/test_analysis_quality_views.py --target tests/unit/operation/test_analysis_store.py --coverage-module dmf_pulse.operation.analysis_quality --coverage-module dmf_pulse.operation.analysis_store --coverage-module dmf_pulse.operation.analysis_cli
uv run --frozen pytest -q -p no:cacheprovider --basetemp=review_pack/resume-inherited-temp tests/unit/operation/test_analysis_admission.py tests/unit/operation/test_analysis_optimizer.py tests/unit/operation/test_analysis_portability.py tests/unit/operation/test_persistent_desk.py tests/unit/operation/test_start.py tests/unit/dashboard/test_dashboard.py tests/unit/dashboard/test_session_bootstrap.py
uv run --frozen pytest -q -s -p no:cacheprovider --basetemp=review_pack/resume-performance-temp tests/performance/operation/test_quality_sql.py
uv build --no-build-isolation
uv run --frozen python scripts/validate_repository.py
uv run --frozen python scripts/scan_secrets.py
git diff --check
```

Use the unchanged `build_repository_manifest` library and canonical serializer
to write the same ticket's new current manifest to `resume/current_manifest.json`;
this changes the capture location only and preserves its sealed predecessor.
Any local mypy blocked by Windows Application Control remains BLOCKED, never PASS;
the authoritative exact-push CI must supply successful strict Linux typing.

The completed external installed-wheel probe uses the unchanged exact baseline
wheel and original900s bound; its additive timing driver proves the harness fix
without reinstalling production. New wheel build and hosted installed gates
remain required. Source-dependent fixture and complete16-shard collection/merged
coverage proofs cannot be replaced by a partial-tier receipt.

Before FULL acceptance, independently review all implemented changes and run
`uv run --frozen python scripts/dev_checks.py full --ci-run <exact-push-run-id>`
from clean unchanged HEAD. No production/model promotion is implied.

Native cleanup has separate pinned source/manifest, dry-run/pilot/after-state
receipts and owner-only durable rollback custody. Review of a plan is insufficient
to claim archived bytes; count only verified completed moves. Unknown dependencies
and incomplete proofs remain HOLD. Never delete the owner archive.
