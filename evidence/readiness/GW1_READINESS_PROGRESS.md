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
| 2.2 availability/start/minutes | IN_PROGRESS | Contract/authority review started after 2.1 acceptance. |
| 2.3–4.5 | NOT_STARTED | Must consume accepted preceding checkpoints in order. |

## Current operational boundary

- Current official-FPL inputs and every combined FPL-derived object remain
  transient/in-memory; raw and derived FPL persistence remain denied.
- Current odds raw payload retention remains denied. Private derived odds use is
  allowed by the active profile; no provider price is publicly disclosed.
- Stage-6 market consensus is available only as
  `PRESEASON_DECISION_SUPPORT / NON_PRODUCTION` and binds actual Session-1
  decision time, exact reviewed fixture identities, parsed-market semantics and
  frozen policy identity.
- No squad, XI, bench, captain, vice-captain or alternative has yet been produced.
- The branch-wide stale GCS-008 current manifest remains a known final
  engineering-acceptance blocker; it will be regenerated only at the designated
  final acceptance checkpoint.

## Exact next action

Implement Checkpoint 2.2 as a structured, reviewed, cutoff-safe current roster
and availability-evidence adapter around the accepted Stage-7 baseline. Preserve
hard-versus-soft override semantics, explicit cold-start/model limitations and
the transient official-FPL rights boundary.
