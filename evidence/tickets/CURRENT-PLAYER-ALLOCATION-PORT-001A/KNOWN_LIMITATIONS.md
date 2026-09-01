# Known limitations

- The governed player prior is historical private-GW1 evidence cut off at
  `2026-08-21T17:30:00Z`; it is not refreshed, production-calibrated, or accepted for this port.
- Individual goal/assist history is partially shrunk to FPL-position priors. BPS auxiliary and
  defensive action rates are incomplete/role-pooled, so Stage-9 confidence remains low.
- Current team membership must still agree exactly with the donor artifact. A subsequent transfer
  blocks binding instead of silently reusing stale team evidence.
- Current Stage 8 supplies team-score distributions, not a full calibrated shot-event process.
  Any bounded save/on-target mechanism added here remains explicitly temporary and low confidence.
- No squad, transfer, lineup, captaincy, chip, or rank optimisation is part of this ticket.
- The separate donor private-GW1 acceptance record is historical provenance only. It does not
  accept this semantic port, its synthetic vertical slice, or any future current-player run.
- No PR, merge, tag, independent review, human acceptance, production persistence, live
  orchestration, or production activation is included.
