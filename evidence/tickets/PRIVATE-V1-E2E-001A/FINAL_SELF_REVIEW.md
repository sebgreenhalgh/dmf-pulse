# Adversarial self-review

## Findings fixed

1. **Machine output was not exposed.** The first CLI printed only the human report. It now has one
   explicit `--output report|json` choice for run and replay, with canonical typed decision JSON.
2. **Real freeze rejection occurred too late.** The CLI now rejects forbidden real retention
   before solver execution, while the artifact boundary retains its independent enforcement.
3. **Runtime packaged artifacts were only transitively trusted.** Execution now binds and checks
   exact Stage-8 policy, player-prior artifact, and historical acceptance hashes.
4. **Report disclosure was incomplete.** The report now identifies current squad/bank/free
   transfers, target/cutoff, resulting squad, formation, joint comparator, score-prior class,
   Stage-9 MC status, warnings, code/input/matrix/decision hashes, and replay command.
5. **Replay accepted an incomplete/extra directory shape.** Verification now requires exactly
   `decision.json`, `input.json`, `manifest.json`, and `report.txt` and the exact three manifest
   payload rows.
6. **Coverage initially missed hostile/error branches.** Typed redaction, source/market failures,
   real retention, atomic write failure, CLI formats, and replay mismatch tests raised the
   ticket-specific branch-aware result from 85% to the required 90% without lowering a gate.

## Rejection attempts

- Fake real-run risk: no current/private payload was read and no synthetic artifact is labelled
  real. The final result is explicitly blocked.
- Scenario corruption: fixtures are joined by canonical IDs; scenario IDs, outcome-draw IDs and
  weights survive; missing fixtures/players block; comparator rows are paired, not independent.
- Transfer accounting: existing selling-price, bank, FT and hit state transitions remain the only
  implementation. No hit is added upstream or twice.
- Squad/lineup/captain: existing exact Stage-11/10/captain boundaries are invoked and the final
  decision is revalidated for 15/11/formation/bench/captain legality.
- Provenance: manual minutes remain LOW and NOT_MODEL_DERIVED; grade-E prior status, GW1 cutoff,
  donor/port acceptance distinction and synthetic score/allocation sources remain prominent.
- Reproducibility: no wall clock, absolute path or worker order enters semantic identity. Replay
  reads only the exact bundle; a network-blocked installed-wheel replay passed.
- Production boundary: no provider automation, persistent real payload, database product state,
  deployment, scheduler, PR, merge, tag, human acceptance, or activation was introduced.

No unresolved P0, P1, or material P2 implementation finding remains. The inability to perform
the required genuine real run is a milestone blocker, not a hidden implementation success.
