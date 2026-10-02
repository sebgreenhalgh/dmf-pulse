# Public prospective evaluation contract

`public-team-strength-prospective-forecast-v1` freezes the authenticated accepted
training dataset, source snapshots and immutable public commits, registry, fitted
artifact, deterministic joint draw set, origin/freeze timestamps and exact fixture
identities. Its sufficient forecast representation is conditional Poisson rates
and weights on the existing 36-goal research scoring support. Plug-in, mixture
and an optional time-eligible accepted league baseline retain distinct identities.
No market/private FPL/player/manager/action fields are accepted.

Commands are `dmf events team-strength prospective-freeze --request <public-json>
--retained-artifact-root <explicit-root>`, `prospective-score --forecast <file>
--forecast-sha256 <immutable-sha> --outcomes <authenticated-public-snapshot>`, and
`promotion-status`. Freeze uses actual UTC now. Date-only public schedules require
freeze before the scheduled day. Source, registry, baseline and fit must be usable
by origin; target outcomes cannot already exist anywhere in training sources or
the training match set. RECONSTRUCTED remains RECONSTRUCTED; LIVE_OBSERVED requires
the accepted dataset's operational temporal lineage. Synthetic tests exercise
both labels without making any real live-observation claim.

Outcomes must be received no earlier than their played date, become usable after
freeze and satisfy the accepted D+2 lag at scoring cutoff. Scores include exact
score log loss, mean team-count log loss, mean goal-count RPS, home/away bias,
1X2/totals/clean-sheet probabilities, binary outcomes, Brier scores and calibration
residuals. Calibration uses the accepted Stage-15 intercept/slope diagnostic;
different draw policies or dataset modes require separate populations. Diagnostics
retain score-report/forecast identities and label rows as forecast-origin samples,
not independent outcomes. Multiple origins for the same match do not establish
independent sample counts. Frozen forecasts are never calibrated or revised.

The rights gate authenticates the unchanged OpenFootball team-strength profile.
Permitted public-source evidence is retained privately in an explicit root using
content-addressed exclusive publication, symlink/containment checks and collision
rejection. This does not grant public redistribution. Any private data class or
non-forecast object fails with PRIVATE_PROSPECTIVE_STORAGE_NOT_AUTHORIZED before
filesystem access. No private forecast/cache/database is introduced.

Promotion status preserves all eight required evidence categories and requires a
separate later human decision. No observation count, one-GW result, historical L8
decision materiality or synthetic proper score activates production.

Validation commands and their exact outcomes are recorded in the final acceptance
log. The prospective tests cover immutable reload, corrected outcomes, temporal
leakage, rehashed forecast-rate tampering, private fields/storage, independent
Poisson log-loss calculation, calibration populations, promotion requirements,
and the actual CLI freeze/score dispatch. The installed-wheel verifier exercises
these commands outside the repository with sockets blocked and a test-only clock.
