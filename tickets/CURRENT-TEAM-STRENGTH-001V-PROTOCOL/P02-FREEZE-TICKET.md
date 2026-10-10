# Ready-to-copy public P02 freeze task

Execute the first standard prospective cohort under the published
CURRENT-TEAM-STRENGTH-001V-PROTOCOL branch, using its exact green publication SHA.
The accepted numerical implementation remains
`3815152e978dd55e1dc1f115055050d4ed6b1735`.

Authenticate protocol
`93b9c2e8a0b0f6c00e1299cb410784daabf1eb04efa01baaab5f10d85d10e029`
and the current externally pinned immutable campaign ledger. Initial ledger SHA:
`e8a8b2cbcfc1e035cdf1b9ec102365ca0704a940976a244684ff4138ee72bcba`.
Preserve P01 and every historical ledger version. Do not score P01 in this task.

Use only governed public OpenFootball EPL acquisition/import and the accepted
canonical fixture registry. Independently authenticate retained input hashes and
reassess source freshness, due completeness and model readiness at actual UTC
execution time. The retained P01 schedule alone does not establish current readiness.
No FPL, Odds, credentials, private provider, live private authority, production
activation or operational draw-count selection is authorized.

Call `plan_cohort` with the authenticated current ledger, public schedule,
registry and actual UTC now. It excludes all previously assigned canonical IDs,
requires NO_SCORE with no outcome, requires current registration and future UTC
dates, sorts date then canonical ID and chooses the first ten (all remaining
eligible fixtures only for a season-end partial cohort). No hand selection.
The offline CLI accepts `events team-strength protocol plan --ledger PATH
--ledger-sha256 SHA --schedule PATH --schedule-sha256 SHA --fixture-registry PATH
--fixture-registry-sha256 SHA`; it does not acquire evidence or freeze forecasts.

Calculate target 12:00 UTC two calendar days before the earliest selected date,
with inclusive six-hour execution window ending 18:00 UTC. If early, report the
calculated window and stop until execution in that window. If missed, retain a
FREEZE_WINDOW_MISSED event via `append_event`, persist its immutable ledger child,
consume the intended cohort ID and use `next_freeze_opportunity` to predict the
next window. At that window re-acquire/reassess and recompute from fresh governed
evidence. A prediction from an old vintage never grants source readiness.

Inside the actual window, call `guard_freeze` before invoking the unchanged
accepted public forecast builder. Use time-safe fitting under the unchanged
model policy and the exact research draw-policy SHA
`444b0b4b8f138bc9188a60e947eb6ff58575c0ceb3f2d825873e9851ddfa49b3`.
Include league baseline, plug-in shadow and parameter-mixture research shadow.
If any accepted product/policy/source/model/date safeguard is unavailable, retain
SOURCE_BLOCKED, MODEL_FIT_BLOCKED or SCHEDULE_BLOCKED; do not substitute.

Use actual forecast_origin, frozen_at and registration time; all must fall inside
the governed window, every selected date strictly after frozen_at.date(). Call
`register_frozen_cohort` before public immutable forecast/ledger retention.
Persist the forecast with accepted public storage and persist the ledger child
with `persist_protocol_evidence`. Retain exact commands, input/forecast/ledger
hashes and P01 preservation proof. Never backdate or replace moved fixtures.

Return the calculated and actual freeze times, selected IDs/original dates, three
product identities, research draw-policy SHA, immutable forecast and ledger paths,
earliest governed scoring eligibility, shadow-only status, and failure/miss evidence.
No scoring, tuning, private acquisition or production activation in this freeze task.
