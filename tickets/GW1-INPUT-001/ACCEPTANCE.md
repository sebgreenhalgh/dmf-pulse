# GW1-INPUT-001 acceptance record

Implementation status: **HUMAN-ACCEPTED FOR BOUNDED PRIVATE 2026/27 GW1
DECISION SUPPORT; NOT ACTIVATED**.

The human-acceptance attestation is
[`HUMAN_ACCEPTANCE.json`](../../evidence/tickets/GW1-INPUT-001/HUMAN_ACCEPTANCE.json).
It binds the reviewed branch `4e8d6ebe58297a66ff02e2b2d5c09981b9c52aba`,
transformation commit `a6b557cd3c0f2a7729c95a34546dd4d9c3aa33a9`, and
candidate artifact SHA-256
`e6a6bd6f5053c8c2db71e982a5eb0b86066232e600ef18296f7f4751ba5bb3d2`.

The candidate artifact deliberately remains `CANDIDATE_NOT_ACCEPTED`: human
acceptance is recorded separately so the reviewed numerical artifact and its
original non-activation provenance are immutable. The acceptance permits only
a league-wide weak Stage-8 regulariser, finite-support prior, and controlled
fallback for private 2026/27 GW1 decision support.

The bounded private acceptance rests on all of the following:

- the exact five pinned OpenFootball EPL files produce 380 completed fixtures
  each, with duplicate fixtures and malformed/negative scores rejected;
- exact-Decimal half-life weighting reproduces the declared league-wide
  10-decimal central rates without hard-coding them as source truth;
- the candidate artifact is hash-bound, records source provenance, and remains
  `CANDIDATE_NOT_ACCEPTED`; the separate attestation has the exact reviewed
  branch, transformation commit, source commit, calibration, model family and
  artifact SHA-256;
- the existing Stage-8 `ScorePriorRequest`, adaptive grid and soft-KL
  projection are reused; no alternative score engine or confidence grade is
  introduced;
- synthetic/replay diagnostics make complete-market, H2H-only, prior-only and
  numerical-fallback behaviour visible; and
- no provider key/request, raw external-data commit, activation, PR, merge or
  player-allocation change occurs.

## Boundaries that remain in force

1. OpenFootball's CC0/public-domain source-owner assertion and its documented
   quality/provenance limitation are accepted only for this bounded private
   use; no wider retention or production-rights conclusion follows.
2. H2H plus totals remain market-primary. H2H-only output remains explicitly
   degraded and materially prior-sensitive; prior-only or numerical fallback
   remains explicitly surfaced.
3. This is not current team-strength evidence, player evidence, or a
   replacement for available market H2H or totals.
4. Separately approved current-player evidence is still required before any
   player goal, assist, minutes, or allocation artifact is considered.
5. A real provider call, production activation, main-branch merge, or any
   wider use needs a separate approval.
