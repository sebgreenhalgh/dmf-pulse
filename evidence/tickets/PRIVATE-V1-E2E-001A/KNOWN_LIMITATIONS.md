# Known limitations

- No genuine current private recommendation exists. Required current FPL/manager/ownership/
  mapping/odds/Stage-7 input was unavailable and no private payload was fabricated.
- Checked target-season rules are `VERIFIED`, while current manager ingestion requires `ACTIVE`
  `FULL_SEASON` authority.
- The only packaged player-allocation prior is `gw1-player-allocation-candidate-v1`: 599 profiles,
  grade E, cutoff `2026-08-21T17:30:00Z`, status `CANDIDATE_NOT_ACCEPTED`, and hard GW1 scope.
- Current FPL/manager rights deny persistent raw/derived real replay storage, while this milestone
  requires a frozen real replay bundle. Only repository-owned synthetic replay is permitted.
- The private V1 objective is one-Gameweek, zero-terminal-value, and exact only within the
  declared bounded incoming-candidate/action space. It is not an unrestricted transfer-market
  optimum or multi-week strategy.
- Stage-10 is the exact tactical evaluator inside Stage 11; captaincy is verified afterward by
  the accepted captain/vice evaluator. No claim of a new fully joint captain-aware squad solver is
  made.
- Cross-fixture injury/dismissal/fatigue/readiness transitions are not propagated; the canonical
  Gameweek composer shares deterministic latent outcome-draw identity under its documented
  approximation.
- Synthetic MC pass was not required by test configuration even though the observed status was
  PASS. Real execution requires the configured real quality gate.

Independent review, exact-final-SHA CI, human acceptance, merge, and any production decision are
separate and remain outstanding.
