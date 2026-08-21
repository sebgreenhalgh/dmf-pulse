# GW1-INPUT-001 acceptance record

Implementation status: **READY FOR INDEPENDENT REVIEW; NOT HUMAN-ACCEPTED**.

This ticket publishes an offline candidate only. It must not be used as an
ACTIVE current-event prior until a human reviews the source-rights record,
historical calibration and downstream readiness decision.

The candidate is accepted for review only if it proves all of the following:

- the exact five pinned OpenFootball EPL files produce 380 completed fixtures
  each, with duplicate fixtures and malformed/negative scores rejected;
- exact-Decimal half-life weighting reproduces the declared league-wide
  10-decimal central rates without hard-coding them as source truth;
- the candidate artifact is hash-bound, records source provenance, and remains
  `CANDIDATE_NOT_ACCEPTED` with all human-acceptance fields empty;
- the existing Stage-8 `ScorePriorRequest`, adaptive grid and soft-KL
  projection are reused; no alternative score engine or confidence grade is
  introduced;
- synthetic/replay diagnostics make complete-market, H2H-only, prior-only and
  numerical-fallback behaviour visible; and
- no provider key/request, raw external-data commit, activation, PR, merge or
  player-allocation change occurs.

## Manual review still required

1. Confirm that OpenFootball's CC0/public-domain statement is sufficient for
   the intended DMF retention and derived-model use, including any upstream
   data-origin consideration outside the repository's own assertion.
2. Review the five file hashes, 1,900-match totals, date/cutoff, rounding and
   source-quality limitations independently.
3. Review the synthetic diagnostic report without treating its output spread as
   a prospective production threshold.
4. Supply separately approved current-player evidence before any player goal or
   assist allocation work begins.
5. Make a separate human acceptance decision before a candidate can become an
   accepted current-event artifact.
