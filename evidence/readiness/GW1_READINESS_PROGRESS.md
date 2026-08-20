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
| 2.3 football-event distributions | ENGINEERING_COMPLETE / OPERATOR_BLOCKED | Capability `008ad0d2…`; Linux run `32325586142` PASS. No governance-accepted current event-prior artifact was supplied. |
| 2.4 FPL-points distributions | LOCAL_COMPLETE / REMOTE_PENDING / OPERATOR_BLOCKED | Exact VERIFIED target-rules and accepted Stage-9 integration passes locally; no governance-accepted current event-prior artifact was supplied. |
| 2.5–4.5 | NOT_STARTED | Must consume accepted preceding checkpoints in order. |

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
- Stage-8 cannot legitimately derive its required Poisson/team-strength rates
  from the available H2H market alone. The repository also has no accepted
  current player-allocation artifact. A governed transient artifact ingress is
  implemented, but the real operator run remains fail-closed until that input
  is governance-accepted and supplied.
- The explicit `PRESEASON_DECISION_SUPPORT` Stage-9 mode now consumes only the
  exact VERIFIED `fpl-2026-27` PLAYER_POINTS capability and preserves the ACTIVE
  plus human-activation production gate. The transient private player-table
  integration passes on synthetic contract fixtures, but no real current table
  exists while the preceding accepted event-prior input is absent.
- No squad, XI, bench, captain, vice-captain or alternative has yet been produced.
- The branch-wide stale GCS-008 current manifest remains a known final
  engineering-acceptance blocker; it will be regenerated only at the designated
  final acceptance checkpoint.

## Exact next action

Freeze and push the Checkpoint-2.4 engineering capability, run the dedicated
Linux gate on that exact SHA, verify remote equality and commit the attestation.
Keep the real current run fail-closed: no points projection may be claimed
without the missing governance-accepted event-prior artifact.
