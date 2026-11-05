# OPR-004 acceptance

Baseline0e3c0fadcf5f84d0527327423c7979463baaabf9; only operation, existing allowed
CLI/dashboard glue, owned tests, documentation and scoped manifest may change.
All numerical/ingestion/rules/solver bytes, original policy material, provider
routes, budgets, PostgreSQL identity/history,24markers and P01 hashes survive.

Required source commands (Python3.13; Windows owner context for private ACL tests):

```
uv sync --all-groups --frozen
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest tests/unit/operation/test_analysis_store.py tests/unit/operation/test_persistent_desk.py tests/unit/operation/test_analysis_admission.py tests/unit/operation/test_start.py tests/unit/dashboard/test_dashboard.py tests/unit/dashboard/test_session_bootstrap.py -p no:cacheprovider
uv run python scripts/generate_repository_manifest.py --ticket OPR-004
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
uv build
uv run python scripts/verify_wheel.py
```

The unchanged20-job CI release additionally supplies the full branch-coverage,
frozen dependency, disposable PostgreSQL migration and external-wheel gates.
Source identity, actual exits, streams, hashes, complete CI jobs and final review
are retained privately; owner-account data never enters public CI.

Native acceptance must exercise a clean installed wheel and the signed release:
start without a token/network; authenticated GW10 history visible;670forecasts
queryable; browser JWT registration/expiry/secrecy/Host-Origin-CSRF-CSP-size
boundaries; explicit eligible owned Refresh through the full unchanged256kernel;
immutable successful snapshot/restart/older selection; failure retention;
single-job/concurrent-click/same-GW denial; old budget/quota/ledger gates;
transactional migration/crash/digest reconciliation; readonly queries/exports;
installation/rollback database preservation; model parity; strict signed runtime
and all-child cleanup. No consumed-GW10 paid test or real credential entry.

Independent technical review must leave no unresolved P0/P1. Verify exact carrier,
signature trust, immutable original control and warehouse, then install using the
existing reviewed private installer. Retain first historical unexplained strict
integrity refusal and never reset/rearm/override a guard. Actual installed browser
and SQL observation completes delivery. No repeated material owner acceptance is
required within the standing policy.

The actual controller must recover authenticated local history when initially
hidden, when hidden during context bootstrap and when visibility returns before
an abort settles. Duplicate visibility/pageshow events produce one bootstrap
and polling interval. SESSION_REQUIRED remains closed, and logout (including
while bootstrap is pending) cannot be reversed by visibility/pageshow. The owned
VM runs the shipped JavaScript with fake DOM/fetch only, never provider access.
Installed-browser acceptance repeats hidden-to-visible recovery without manual
reload and leaves the genuine retained-data workspace visible.
