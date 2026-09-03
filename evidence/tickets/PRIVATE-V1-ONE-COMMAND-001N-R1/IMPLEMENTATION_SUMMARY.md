# PRIVATE-V1-ONE-COMMAND-001N-R1 implementation summary

## Outcome

The one-command service now acquires and authenticates its single OpenFootball score-prior source
result immediately after current odds and before identity resolution or Stage 7. That unchanged
result is retained only in memory. Once canonical identities and Stage-7 minutes exist, the
service performs the existing current/future fixture binding without any new provider call.

## Root cause and correction

Before remediation, FPL and odds acquisition were followed by identity resolution and potentially
long three-Gameweek Stage-7 computation. Only then did `CurrentScorePriorService.build` make its
four real OpenFootball calls through the cutoff-guarded clock. A Stage-7 duration longer than the
remaining five-minute acquisition window therefore caused a correct `POST_CUTOFF` failure.

After remediation, all three required external input classes are acquired before long deterministic
work: FPL, odds, then the one four-resource OpenFootball result. Fixture-specific score-prior
bundles are still constructed after identity resolution and Stage 7 from that same authenticated
result. No service, parser, rights, timestamp, hash, model, projection, optimization, or horizon
contract changed.

## Timing and provenance proof

The live-shaped injected-clock regression acquires FPL, odds, and all four OpenFootball resources
at the unchanged cutoff, then simulates both seven-minute and nine-minute Stage-7 durations. Both
runs reach the rolling recommendation boundary; no provider event occurs at or after Stage-7
start; OpenFootball transport count is exactly four in each run; all nine synthetic current/future
fixture bundles bind the same source semantic hash; and both durations produce the same sealed
rolling execution semantic hash.

The retained result keeps its actual request, receipt, validation, usable, cutoff, commit, rights,
transport-count, and semantic provenance. Inherited tests continue to reject real acquisition or
receipt after cutoff, unavailable rights, malformed provenance, and source usability after bundle
`as_of`.

## Compatibility and scope

The existing one-command tests, rolling/CLI matrix, and full Stage-11 unit/golden/property/contract
matrix pass. These protect one-GW output behavior and all accepted 001N FT, bank, squad, recourse,
terminal, future-price, no-information-revelation, candidate-pruning, no-chip, and rank-off
semantics. Production scope is one orchestration file; tests, ticket contracts, plan, and bounded
evidence are the only other changes. No provider body or private runtime value is retained.
