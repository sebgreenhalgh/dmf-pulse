# GW1-PLY-002 hostile review

Resolved findings:

- A naive `tag 101` count includes goalkeeper-side Save attempt records. Goal
  calibration now counts only scorer-side Shot/Free Kick events, separates tag
  102 own goals and excludes Free Kick/Penalty.
- The source's formation summary counters are not used as player totals; they
  are inconsistent with event aggregates. Exposure comes only from the listed
  XI/substitutions/dismissal timeline.
- The source role taxonomy has only four broad positions. No CB/FB_WB/DM/CM/AM/
  WINGER/CF inference, name-based mapping or current-player join is attempted.
- Save rate is constrained to GK pools. Non-GK profile rows now carry explicit
  position-not-applicable zero rather than a Jeffreys smoothing residue.
- Wyscout tag 301 remains broad source assist propensity. Current FPL assist
  eligibility stays in Stage 9.
- Blocks, recoveries, big chances, causal errors, goal-line clearances, fouls
  won, inside-box save fraction and being tackled are visibly unsupported;
  compatibility fallbacks cannot be mistaken for calibrated observations.
- Moment kappas are retained only as diagnostics and not labelled calibrated.

Open limitations for human review are historical single-season transferability,
coarse roles, provider-definition mismatch, the 48,033 unexposed-event
exclusions, incomplete BPS field coverage, and the pending official current
player-history rights decision.
