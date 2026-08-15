# OPT-010 acceptance contract

This file freezes gates; it does not assert that implementation has passed them.

## Scope and authority

- Parent is exactly `a33f46cd7ec190fbd4959e2840527116f22547ac`; implementation branch is
  `stage/A10/OPT-010-one-gameweek-optimiser`.
- Only `tickets/OPT-010/ticket.yaml` may define implementation scope, status, caps and allowed
  files. `OPT-010_SOL_PLAN.md` supplies the reconciled contract detail.
- No Stage-9 contract, rules capability schema, dependency lock or migration changes.
- Objective is exactly `EXPECTED_CURRENT_GAMEWEEK_MANAGER_POINTS` and every result labels its
  bounded, non-season, non-rank, non-price and non-chip meaning.

## Exact reference/test rules and golden examples

The implementation fixture is a complete, integrity-checked `REFERENCE_ONLY` or test-synthetic
compiled ruleset. Its values are the ones frozen in the ticket. It is not evidence about
2026/27 production rules.

Use symbolic players with canonical UUIDs but these fixed roles:

- squad: goalkeepers `G1,G2`; defenders `D1..D5`; midfielders `M1..M5`; forwards `F1..F3`;
- standard XI: `G1,D1,D2,D3,M1,M2,M3,M4,F1,F2,F3` (3-4-3);
- five-midfielder XI: `G1,D1,D2,D3,M1,M2,M3,M4,M5,F1,F2` (3-5-2);
- bench always has designated `G2` plus three explicitly ordered outfield players;
- all unmentioned players appear and score zero.

Required exact goldens:

1. The valid generated formation set is exactly
   `3-4-3,3-5-2,4-3-3,4-4-2,4-5-1,5-2-3,5-3-2,5-4-1`; any XI with two defenders is illegal.
2. With standard XI, bench `G2,M5,D4,D5`, only absent `M1`, and appearing `M5`, slot 1 replaces
   `M1`.
3. With 3-5-2 XI, bench `G2,F3,D4,D5`, only absent `D1`, slot 1 `F3` is skipped because it would
   leave two defenders; slot 2 `D4` replaces `D1`.
4. With the same 3-5-2 XI/bench, absent `D1` and `M1`, both appearing `F3` and `D4` enter: `F3`
   replaces `M1`, then `D4` replaces `D1`; final shape is 3-4-3. This freezes the test-only
   multiple-absence interpretation and is not a target-season claim.
5. If `G1` is absent and `G2` appears, `G2` replaces `G1`; no outfielder can replace a goalkeeper.
6. Captain appearance in any Gameweek fixture applies multiplier 2. If captain is absent and
   vice appears, vice receives it. If both are absent, neither receives a multiplier.
7. Two equal-weight captain scenarios with manager totals 20 and 8 have exact expectation 14.
8. An appearing player with negative Stage-9 points remains counted; zero points never implies
   nonappearance.
9. Blank Gameweek returns exact zero; shared-draw/DGW uses accepted aggregate Gameweek points and
   `player_appeared` without fixture reconstruction.

## Search and status gates

- Fixed reference squad has exactly 363,000 legal saved tactical configurations before any
  proven algebraic decomposition.
- Packaged caps are 12 squads, 5,000,000 tactics, 20,000,000 scenario-score operations and 16
  returned exact ties.
- Preflight occurs before combination materialization. Any exceeded cap is `RESOURCE_LIMIT`,
  guarantee `NONE`, with no recommendation, ties or incumbent.
- Exact numerator equality defines ties; there is no tolerance.
- `PASS` is eligible. Stage-9 `CONTINUE` is `BLOCKED/UPSTREAM_MONTE_CARLO_CONTINUE` before search.
  Stage-9 `BLOCKED` is `BLOCKED/UPSTREAM_MONTE_CARLO_BLOCKED` before search.
- Current production target is
  `BLOCKED/MANAGER_TACTICS_CAPABILITY_UNAVAILABLE` with no recommendation. `PLAYER_POINTS` cannot
  authorize manager tactics.
- A future passing `FULL_SEASON` capability still cannot produce an OPT-010 production plan while
  the accepted Stage-9 Gameweek cutoff identity is unprovable; return
  `BLOCKED/STAGE9_CUTOFF_LINEAGE_UNAVAILABLE`.

## Independent verification

- Legality validator does not import solver, candidate generation or tactical enumeration.
- Test oracle does not import production search, autosub or legality helpers.
- Hypothesis runs 100 deterministic, deadline-free examples and compares exact objective,
  complete optimum signature set, scenario scores and legality.
- Every semantic mutation invalidates the appropriate embedded/detached identity.
- Identical inputs produce byte-identical semantic results. Wall time is evidence telemetry only.

## Coverage and quality

- Existing repository coverage gate remains at least 90%.
- `dmf_pulse.optimisation` branch coverage is at least 90%.
- Each critical rules/autosub/legality/tactics/artifact file named in the ticket reaches at least
  95% branch coverage.
- No broad coverage pragma, skipped required case, network call, secret, path escape, artifact
  overwrite, dependency or migration drift.

## Literal acceptance commands

Run, record and validate every command in `tickets/OPT-010/ticket.yaml` under
`acceptance_commands`, in order. Docker teardown is mandatory in a PowerShell `finally` block
even after an earlier PostgreSQL failure. The CLI acceptance helper must execute both public
commands with repository fixtures, validate stable exit codes and run the independent artifact
checker. No command may be silently skipped.

Independent review must have no unresolved P0/P1. Human acceptance and merge remain separate.
