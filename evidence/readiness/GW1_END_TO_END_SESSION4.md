# GW1 Session 4 - end-to-end orchestration and prospective evaluation

## Shared operator path

`run_gw1_decision_pipeline` is the sole Stage-6 through Stage-10 composition
service. `dmf gw1 run` prepares and completes Session 1, supplies explicit
availability and event-approval callbacks, and calls that service. There is no
serialized FPL handoff or duplicate CLI model implementation.

The command preflights the declared commit shape, governance-accepted event
prior, tracked rules compilation, exact canonical rules/file/capability hashes,
and Monte Carlo policy file hash before it spends a provider request. It then
performs one live Odds retrieval, exact identity review, market consensus,
availability/minutes, event distributions, FPL points, projection acceptance,
three initial-squad portfolios, XI, bench and captain/vice in one process.

All private reviews and detailed decision content are transient terminal output.
The command accepts no API-key or password option, performs no official-FPL
automation, saves no detailed player/squad object, uses no chip and has no FPL
account integration.

## Stage-12 prospective boundary

A receipt is created only for a successful accepted decision. Its information
cutoff is the last approved Stage-8/9 decision-information boundary; its record
time is taken after Stage 10. Completion after the official GW1 deadline fails
with `POST_CUTOFF` before persistence.

The content-addressed `receipt.json` contains only UTC timestamps, code commit,
rules/capability, Session-1/market/availability/event/config/projection/
gameweek/scenario/decision hashes and explicit no-content flags. It contains no
FPL player, price, squad, XI, captain, provider payload or raw data. Existing
different bytes cannot be overwritten.

## Operator contract

`docs/operations/gw1_full_decision_run.md` is the exact Windows PowerShell
runbook. It covers frozen environment sync, pinned PostgreSQL, process-only
credential input, non-disclosing diagnostic, browser-only FPL capture, three
explicit reviews, accepted event-prior input, 1,000-scenario execution,
decision/receipt interpretation, controlled failures, safe capture deletion and
secret clearing.

External operator inputs remain:

1. current manually captured official bootstrap/fixtures;
2. process-scoped The Odds API credential and disposable PostgreSQL reference;
3. explicit team/fixture and availability-evidence reviews;
4. a current independently governance-accepted event-prior artifact.

`REAL_CREDENTIALLED_PROVIDER_CALL = OPERATOR_CHECKPOINT`.

## Validation

- Shared synthetic pipeline acceptance - `1 passed` in `83.45s`; the small MC
  budget blocks cleanly and creates no prospective directory.
- Prospective receipt and CLI contract - focused PASS; isolated installed wheel
  loads from site-packages and exposes `dmf 0.2.0` plus `dmf gw1 run --help`.
- Current/Stage-12/orchestration group - `160 passed` in `533.26s`.
- Final exact-SHA Linux validation - `PENDING_FINAL_PUBLICATION`.
