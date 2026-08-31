# CURRENT-AVAILABILITY-001B known limitations

- The uncertainty distribution is authored by a private operator and is not calibrated, learned,
  inferred, smoothed, or independently verified by this adapter.
- Canonical fixture/team/player UUIDs are structurally checked, but this offline command does not
  authenticate them against a live current-FPL catalogue.
- The operator must protect the input and output directory: the canonical input artifact retains
  the supplied private provenance and judgements for reproducibility.
- The adapter itself provides no database persistence, retention lifecycle, reviewer workflow, or
  production audit service. The explicit transient artifacts are the reproducibility record.
- Confirmed fixture cancellation does not produce a coherent playable Stage-7 XI and is not
  converted into a minutes context by this bridge.
- The normal current Stage-7 model remains blocked on an accepted real historical/current-player
  evidence path. This bridge is removed from use when that model-derived path becomes available.
- No player event allocation, Stage 9 scoring, FPL optimisation, live scheduling, UI, or production
  orchestration is implemented.
- Engineering completion is not independent review, human acceptance, PR authorization, merge,
  tag, or production activation.
