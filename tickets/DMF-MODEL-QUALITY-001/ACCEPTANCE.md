# DMF-MODEL-QUALITY-001 acceptance

Run in the isolated research checkout with Python 3.13 and a workspace-local
`UV_CACHE_DIR`; use offline cached dependencies. Do not initialize the canonical
warehouse, contact a provider or read credentials. Temporary paths below are
fresh, explicit subdirectories of this checkout's ignored review_pack.

```
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest -q -p no:cacheprovider --basetemp=review_pack/quality-seal-temp tests/unit/operation/test_analysis_quality.py tests/unit/operation/test_analysis_quality_views.py tests/unit/operation/test_analysis_store.py --cov=dmf_pulse.operation.analysis_quality --cov=dmf_pulse.operation.analysis_store --cov=dmf_pulse.operation.analysis_cli --cov-branch --cov-fail-under=0 --cov-report=term-missing --cov-report=json:review_pack/quality-final-coverage.json
uv run pytest -q -p no:cacheprovider --basetemp=review_pack/inherited-final-temp tests/unit/operation/test_analysis_admission.py tests/unit/operation/test_analysis_optimizer.py tests/unit/operation/test_analysis_portability.py tests/unit/operation/test_persistent_desk.py tests/unit/operation/test_start.py tests/unit/dashboard/test_dashboard.py tests/unit/dashboard/test_session_bootstrap.py
uv run pytest -q -s -p no:cacheprovider --basetemp=review_pack/quality-performance-temp tests/performance/operation/test_quality_sql.py
uv build --no-build-isolation
uv run python scripts/generate_repository_manifest.py --ticket DMF-MODEL-QUALITY-001
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
git diff --check
```

Build isolation is disabled only for the offline QA build: Hatchling is the
unchanged frozen build backend, already installed by frozen sync. Do not modify
the lock or install another type-checker version to satisfy a host policy.
If Windows Application Control refuses mypy/librt, retain the actual failure and
require the unchanged Linux CI strict typing result; do not classify it as pass.

Require >=90% focused quality-module branch and line coverage, plus meaningful
store/CLI compatibility coverage. The unchanged hosted CI supplies the full
global/component branch coverage, disposable PostgreSQL migration matrix,
performance and installed-wheel gates. A source review without those gates
is not release acceptance. Test failures and unavailable checks remain visible.

External wheel verification must install the exact built wheel with frozen
runtime dependencies into a fresh QA environment outside the checkout, assert
the imported package is from that environment, exercise `dmf analysis quality`
on an owned v1 and v2 warehouse, preserve their bytes, refuse missing runs/files,
and make no credential/provider/model calls. Existing comprehensive verifier
may be invoked through `scripts.verify_wheel.verify_wheel(report_path=...)` to
avoid overwriting accepted historical DAT-003 package evidence.

Research-copy migration must preserve exact snapshots, publication digests and
all v1 player rows; repeated migration changes no bytes; forced DDL failure,
corrupt digests and ambiguous identities roll back entirely. New metric joins
must maintain exact official/canonical player, fixture and GW grains. A 760-player
schema-valid synthetic summary SQL stress test must stay within the existing
five-second per-query bound; it is not full snapshot/model validation.

The public review archive is capped at 20 flat files and 32 MiB total, with
detached SHA256 and ZIP CRC verification. No private forecasts or database copy
enters it. Independent review must have no unresolved P0/P1 for the research
slice. The currently signed v1 reader rejects a migrated v2 database; production
rollout and rollback compatibility require separate acceptance before activation.
