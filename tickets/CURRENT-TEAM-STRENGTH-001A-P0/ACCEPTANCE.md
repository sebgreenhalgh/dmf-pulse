# CURRENT-TEAM-STRENGTH-001A-P0 acceptance

Engineering acceptance requires all of the following:

1. The branch starts at immutable parent `99418f3316277f4dae347d80358d5dd5a09655b2`, which is
   the accepted CURRENT-SCORE-PRIOR-001A merge, without using or altering the dirty availability
   worktree.
2. The separate `openfootball_football_json_team_strength_v1` profile records Sebastian's exact
   approval, private purpose, CC0 source identity, permitted retention and operations, and public
   display/redistribution denials; the earlier score-prior profile is semantically unchanged.
3. The reviewed identity artifact contains 42 distinct nondeterministic UUIDv7 canonical clubs,
   56 exact source aliases/records, 14 additional spelling variants, 17 source seasons, 20
   season-scoped current FPL external IDs, and zero unresolved or ambiguous mappings.
4. Every alias and season maps exactly once; aliases converge across spelling changes,
   relegation, and re-promotion; unknown, case-varied, duplicate, ambiguous, reordered, or
   semantically tampered inputs fail closed.
5. Display names and current FPL IDs are not canonical IDs; there is no fuzzy, Levenshtein,
   casefold, deterministic name-hash, or current-season membership identity rule.
6. LIVE_OBSERVED finality requires immutable commit/file hashes, pre-cutoff receipt and usability,
   exact fixture/club mapping, a recognized final score, no non-final or unknown status, and
   eligibility no earlier than the second UTC midnight after the played source date.
7. FRESH is exact-valid with no missing due results and retrieval age at most 24 hours; DEGRADED
   is over 24 and at most 72 hours; every missing/ambiguous/invalid input or age over 72 hours is
   STALE_BLOCKED. Repository age alone is not freshness.
8. Materiality is locked at 1% calibration/subgroup harm, 0.15 player xP/GW, 0.50 points over
   three Gameweeks or any root-action switch, and the later of 10 Gameweeks and 100 labelled
   fixtures, with separate human production approval always required.
9. The selected provisional model family and reconstructed empirical evidence are recorded only;
   plug-in prediction remains shadow-only and `CURRENT-TEAM-STRENGTH-001U` is required before
   production promotion.
10. No team-strength fitting, solver, decay, covariance, lambda, score-prior generation, Stage 8,
    private-v1, Odds, private FPL, database, or production-activation behavior is introduced.
11. Focused and inherited tests, coverage, Ruff, strict mypy, build, clean installed-wheel,
    frozen sync, repository validation, authority manifests, secret scan, and `git diff --check`
    pass without deterministic-acceptance network access.
12. Fresh independent review returns
    `CLEAR_FOR_CURRENT_TEAM_STRENGTH_001A_IMPLEMENTATION` with no unresolved P0/P1/material P2.
13. The implementation and sealed-evidence commits are pushed, local and remote SHAs match,
    exact-SHA CI is green, and the isolated worktree is clean. No PR, merge, or accepted tag exists.

This closes precursor governance only. It does not implement or activate CURRENT-TEAM-STRENGTH-001A.
