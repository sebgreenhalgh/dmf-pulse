# CHIP-014 checkpoint 14.05 — Wildcard

## Capability

Wildcard is evaluated as a permanent Stage-11 manager-state reset against the best legal route
that retains the token at the current deadline. The comparator explicitly admits:

- immediate Wildcard;
- ordinary current transfers followed by a delayed Wildcard after named information;
- a Free Hit bridge followed by a delayed Wildcard;
- hold and allow-expiry routes.

Each route keeps current points, transfer hits, permanent squad value, future transfer-hit value,
price-route value, flexibility, forced-transfer value, Bench Boost synergy, Free Hit synergy,
Triple Captain synergy, terminal value, information value, delay cost, affordability loss, expiry
loss and execution risk separate. The evaluator then reconciles those components exactly to the
immediate-versus-retained exercise advantage.

The immediate reset delegates squad, bank, free-transfer and ownership-cohort transitions to the
accepted Stage-11 transition implementation. Incoming players receive new purchase cohorts at the
current node price; retained and closed ownership history remains append-only.

## Direct verification

- Focused Wildcard acceptance and fail-closed contract tests: `58 passed`.
- Complete Stage-14 chip unit/property confidence: `207 passed`.
- New Wildcard evaluator branch coverage: `94.19%` (`81 / 86`).
- New Wildcard model branch coverage: `94.59%` (`70 / 74`).
- New Wildcard evaluator statement coverage: `97.30%` (`180 / 185`).
- Complete chip-package statement coverage: `96.29%` (`1609 / 1671`).
- Ruff changed-file gate: PASS.
- Ruff changed-file format gate: PASS.
- Strict mypy for changed production modules: PASS.
- `python -m compileall`: PASS.
- `git diff --check`: PASS before the capability commit.

The focused suite covers:

- immediate Wildcard as the clear optimum;
- one-free-transfer repair beating Wildcard;
- delayed use after future information;
- affordability loss from waiting;
- exact permanent squad/bank/free-transfer reset;
- incoming purchase-price cohort replacement;
- expiry pressure;
- positive and negative Wildcard–Bench Boost synergy;
- Free Hit bridge then Wildcard;
- common-scenario and rules lineage;
- transfer-event, timing, token, inventory and definition failures;
- malformed squad, club, budget and state transitions;
- route/evaluation arithmetic and semantic-hash tampering.

## Status

Checkpoint `14.05` is published on the canonical Stage-14 branch at capability commit
`0449dd7c47ae983a78fb8ef9098ce604ae3022db`. Publication was non-force and the remote tree
contains the Wildcard implementation, tests and evidence. Independent review and human acceptance
remain pending; no merge, PR or tag was created.
