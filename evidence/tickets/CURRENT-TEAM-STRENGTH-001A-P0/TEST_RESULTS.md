# Test and quality results

- Focused OpenFootball/config/governance suite: `195 passed`.
- Focused coverage: 576/599 statements (`96.16%`), 141/154 branches (`91.56%`), combined
  branch-aware coverage `95.22%`.
- Broader non-PostgreSQL ingestion population: `972 passed`.
- Inherited Stage-8/football-events population: `212 passed`.
- Ruff format: `698 files already formatted`.
- Ruff lint: all checks passed.
- Strict mypy: no issues in `260` source files.
- Frozen all-groups sync: `40` packages checked.
- Build: `dmf_pulse-0.2.0.tar.gz` and `dmf_pulse-0.2.0-py3-none-any.whl` succeeded.
- Clean installed-wheel verification: PASS outside the repository, exact packaged rights,
  identity and policy loaded, zero network calls.
- Source generation: deterministic/idempotent against committed artifacts.
- First-party secret scan: zero findings.

An exploratory unconstrained local `pytest -q` was stopped after database-backed tests reported
setup errors because Docker Desktop was not running. It is not recorded as a passing gate. The
ticket's relevant deterministic local populations above are green; the repository CI PostgreSQL
service and exact-SHA jobs remain the controlling full-platform check.
