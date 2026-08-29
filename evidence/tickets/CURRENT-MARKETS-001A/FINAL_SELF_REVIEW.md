# CURRENT-MARKETS-001A second-remediation engineering self-review

## Reproduced current findings

- CMR-IR-003: before the fix, a post-receipt newer H2H alias suppressed an older valid alias.
  Now market and bookmaker-fallback timestamps are filtered before grouping; the valid older alias
  remains, all-future aliases contribute nothing, valid newest/tied cases are deterministic, and
  conflicting ties remain quality-blocked.
- CMR-IR-007: first-remediation evidence claimed committed pending/dirty Session tests that were
  absent. Reviewer-only exploratory probes are now distinguished from the two named committed
  `autoflush=True` PostgreSQL tests. Pending/dirty state remains unflushed and is rolled back;
  relevant canonical/mapping/operator/market row counts and captured DML remain unchanged/empty.
- CMR-IR-008: before the fix, a coherently rehashed event participant plus H2H-label swap changed
  HOME consensus while the accepted 001B map remained unchanged. Exact event identity, both team
  sides, official-FPL orientation and kickoff now reconstruct in `build()` and `verify()`; the old
  attack blocks. The independent local outcome-label guard remains.
- CMR-IR-009: before the fix, operator resolution reduced two occurrences to the earliest time.
  The resolver now proves every target occurrence against one row, ignores unrelated/non-occurring
  events, rejects half-covered ranges, and binds a target-occurrence applicability digest.

## Preserved regressions

CMR-IR-001/002/004/005/006 remain closed: local H2H labels, complete temporal binding,
HUMAN_VERIFIED authority, exact official-FPL scope, and exact approved Odds rights all pass their
positive and hostile matrices. H2H vig/consensus, totals binary power/underround/fair/fallback,
exact complements, half-goal gating, price/line/quality/source mutations, ordering and rehashed
tamper verification remain green.

## Coverage and database boundary

The focused suite passed 110 tests. Raw current-module statement coverage is 818/841
(97.26516052318668%); raw branch coverage is 230/248 (92.74193548387096%). These are separate
figures and both exceed 90%. Newly fixed H2H pre-ranking, cross-source bridge and multi-occurrence
operator paths have direct tests.

Product source contains no Session add/flush/commit and no SQL INSERT/UPDATE/DELETE. The resolver
uses SELECTs only. PostgreSQL tests report no autoflush, DML, persistence, canonical creation,
external identifier/operator creation, normalisation run, market consensus or current-market row.

## Rights, disclosure and scope

Rights remain PRIVATE and TRANSIENT_IN_MEMORY; persistent/derived/raw storage, cache, backup,
public display and redistribution remain denied. Runtime records no network, persistence or
database write. Summary/error string, repr, object and JSON surfaces expose no official fixture,
provider event/team, bookmaker, price, mapping or manager-private data.

No sealed upstream source, Stage-6 mathematics, GCS-008, migration or future-stage implementation
changed. Stage-7 remains DATA_BLOCKED; GCS-008 was not executed live; score prior remains exactly
`NO_ACCEPTED_CURRENT_SCORE_PRIOR`; player allocation, Stage 9 and optimisation were not started.

## Engineering finding accounting

- P0 unresolved/new: 0 / 0.
- P1 current engineering-closed/unresolved: CMR-IR-003 and CMR-IR-008 / 0.
- Material P2 current engineering-closed/unresolved: CMR-IR-007 and CMR-IR-009 / 0.
- New P1/material P2/P3 found by this self-review: 0 / 0 / 0.

This is engineering closure at `562e5a586881d9e462075ffd5dad01401b265ff3`, not independent
confirmation.

`CURRENT_MARKETS_001A_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`
