# GW1 2026/27 readiness — master progress

## Immutable context

- Canonical branch — `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable programme parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.
- PR, merge and production activation — `NOT_AUTHORIZED / NOT_PERFORMED`.

## Checkpoint matrix

| Checkpoint | Status | Controlling evidence |
|---|---|---|
| 1.0–1.3 | COMPLETE | Existing Session-1 progress and accepted remote evidence. |
| 1.4 identity integrity | COMPLETE | Capability `16560a1f…`; Linux run `32313356458` PASS. |
| 1.5 Session-1 workflow | COMPLETE | Capability `db4ef85f…`; Linux run `32315608960` PASS. |
| 2.1 current market consensus | COMPLETE | Remediated capability `2858e6f1…`; Linux run `32317678585` PASS. |
| 2.2 availability/start/minutes | COMPLETE | Capability `e7c40a03…`; Linux run `32319850997` PASS. |
| 2.3 football-event distributions | IN_PROGRESS | Authority and accepted Stage-8 contract review started after 2.2 acceptance. |
| 2.4–4.5 | NOT_STARTED | Must consume accepted preceding checkpoints in order. |

## Current operational boundary

- Current official-FPL inputs and every combined FPL-derived object remain
  transient/in-memory; raw and derived FPL persistence remain denied.
- Current odds raw payload retention remains denied. Private derived odds use is
  allowed by the active profile; no provider price is publicly disclosed.
- Stage-6 market consensus is available only as
  `PRESEASON_DECISION_SUPPORT / NON_PRODUCTION` and binds actual Session-1
  decision time, exact reviewed fixture identities, parsed-market semantics and
  frozen policy identity.
- Stage-7 current minutes are available only as an explicit empty-history
  cold-start against the frozen synthetic TEST/REPLAY baseline. The output is
  non-production, carries confidence grade D for unobserved current players and
  makes no production-calibration claim.
- No squad, XI, bench, captain, vice-captain or alternative has yet been produced.
- The branch-wide stale GCS-008 current manifest remains a known final
  engineering-acceptance blocker; it will be regenerated only at the designated
  final acceptance checkpoint.

## Exact next action

Implement Checkpoint 2.3 as a transient current-fixture adapter around the
accepted Stage-8 market-constrained score-distribution baseline. Bind the exact
Stage-6 consensus and Stage-7 minutes identities, preserve all cold-start and
market-coverage limitations, and make no player-allocation or Stage-9 claim.
