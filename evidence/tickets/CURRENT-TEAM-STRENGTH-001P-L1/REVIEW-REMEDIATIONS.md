# L1 adversarial review remediations

Independent reviewer: `/root/l1_execution_review`. No providers/credentials used.
Initial review withheld execution clearance pending three findings:

1. P1: a newly retrieved historical season could mask a 75-hour-old current EPL
   snapshot under inherited corpus-wide latest-retrieval freshness. L1 now requires
   the current-season receipt to be the newest receipt before dataset construction.
   Coherently resealed 25-hour and 75-hour counterexamples both fail closed.
   Accepted P0/001A policy and mathematics are untouched.
2. Material P2: pre-private SOURCE_STALE returned the private execution-failure
   status. It now returns TEAM_STRENGTH_PUBLIC_PREFLIGHT_BLOCKED, with unconsumed
   attempt and zero private request counters.
3. Material P2: an unused temporary-directory snapshot did not prove zero private
   writes. The complete generated-data L1 execution now runs under a write-denying
   builtins/io/os-open guard; separate adversarial tests prove attempts to write at
   arbitrary destinations are caught. Public-source retention is tested separately.

Self-review additionally caught and fixed two inherited boundary requirements:
run IDs exclude the attestation's `#`, and Odds commence filters require whole-second
UTC timestamps. The L1 five-minute window end is rounded down; the exact human
attestation remains a separate safe summary/authority field. The E2E clock includes
microseconds and advances beyond acquisition cutoff once real Stage-7 fitting starts.

No ignored P0/P1/material-P2 finding is accepted. Final independent clearance and
all mandatory exact-SHA CI jobs remain separate publication/execution gates.
