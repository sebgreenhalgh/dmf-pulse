# 001P implementation boundaries

The accepted private execution contracts intentionally permit only synthetic and authenticated
league-prior sources. Their validators must not be weakened to make team strength selectable
through ordinary construction. The explicitly authorized alternative is a private resolver backed
by a separately authenticated shadow input, while the original execution remains frozen.

The baseline must call `PrivateV1RollingRecommendationService()` with no resolver. The shadow
uses a fresh service and the authenticated private score-prior resolver only. Both use the default
stale player allocation; combining this with the R9C allocation resolver is prohibited. Neither
the CLI nor the one-command factory imports or selects the comparison.

The separate input must bind the original execution SHA, complete oriented horizon fixtures,
the accepted public model envelope/state and fixture registry, unmodified public fixture bundles,
the sealed P0 FPL-ID crosswalk, cutoff and current source assessment. At the service boundary,
authenticate it against the exact baseline input before any projection. The shadow run's lineage
must identify this actual combined input, never falsely claim the baseline-only input generated
the changed projections. Ordinary lineage hashes must remain unchanged when the seam is absent.

Missing fixture coverage blocks the entire shadow world. Integrity, post-cutoff, wrong-season,
wrong-competition and tampering errors are hard failures. Stale/unavailable governed source
evidence is a typed unavailable result, not a silent league/team-strength mixture.

Randomness control uses the unchanged Stage-9 implementation: root seed, fixture-derived child
seed, scenario index and named child streams. Scoreline sampling uses the same exact integer
quantile draw over each alternative Stage-8 simplex. Participation is unchanged. Different goal
counts may consume different subsets of event draws; the common named coordinates and their
draw algorithm remain identical. Do not equate sampled outcomes or variable draw consumption
with a different randomness policy. Test the actual common draw coordinates, not just seed labels.

The prepared one-command context already freezes fitted Stage-7 projections. Reuse those
projections in both worlds; no fitting/provider acquisition in comparison. Synthetic fixture
construction may differ from retained real provider data but must retain explicit TEST authority.
No synthetic shortcut may replace the real Stage-8/9/10/11 pipeline.

The existing A1 world-result conventions may be reused for signatures/control hashes, but its
four-world wrapper and mandatory candidate-universe equality must not be reused for 001P.
Candidate screening is an allowed downstream consequence. Classification must disclose root
action changes with different screens as confounded.

Safe output contains approved decision-level information and aggregates only. Internal
player/GW rows can be inspected in synthetic tests but are not the live-safe serialization.
Timing is a separate nonsemantic execution diagnostic. No persistence or provider implementation
belongs in the comparison module.
