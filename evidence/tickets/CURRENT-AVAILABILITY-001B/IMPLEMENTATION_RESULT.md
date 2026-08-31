# CURRENT-AVAILABILITY-001B implementation result

Implementation checkpoint: `069b721b8958c5771ddb45449ee8519ed348194a`, a normal direct
descendant of immutable parent `99418f3316277f4dae347d80358d5dd5a09655b2`.

## Delivered capability

The private operator supplies one strictly validated fixture document containing both teams and
canonically ordered weighted lineup/minutes scenarios. Positive integer counts must total exactly
256 per team. Every expanded scenario uses the same roster, exactly 11 starters, one starting
goalkeeper, nine bench players including one goalkeeper, explicit OUT membership, and integer
official minutes in 0..90. No probability floats, normalization, RNG, smoothing, regression,
shrinkage, interpolation, league-average fill, or historical-observation fabrication occurs.

The adapter deterministically derives the existing Stage-7 player summaries and full 91-bin PMF.
All players are grade D and include `MANUAL_TRANSIENT_OVERRIDE`. The team family is the closed,
truthful identifier `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1`. Its dataset hash binds the complete
canonical manual input; its model-artifact compatibility hash
`843e98f9849f1420b8cc573f44cb6ee23ed8f26e659bfba1b11de81fa2cc15d2` binds the governed
transformation policy, not a learned model.

Fixture/team/as-of/hash checks remain active in `Stage7MinutesContext`. A synthetic integration
test proves manual scenarios -> Stage-7 projections -> Stage7MinutesContext -> the existing
`ScoreDistributionService.project()` path. Existing empirical-Bayes outputs retain their original
fields, serialization, hash semantics, and accepted family.

## Operator surface

```text
dmf availability manual-override --input fixture_manual_minutes.json --output-dir artifacts/dmf-private-transient
```

The command emits canonical input, both team projections, the Stage-7 context, and a provenance
manifest only below a resolved path containing an exact `dmf-private-transient` component. Outputs
are immutable and preflighted as one set; malformed, unsafe, or conflicting requests exit nonzero.

## Status

`CURRENT_AVAILABILITY_001B_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

This is private transient decision support only. It is not model-derived, production-ready,
human-accepted, merged, tagged, or production-active.
