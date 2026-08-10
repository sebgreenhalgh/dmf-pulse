# MIN-007R3E implementation plan

- Harden candidate identity to a one-to-one canonical UUID/player-key mapping.
- Validate START/BENCH Decimal constraints at explicit precision 256 without changing the precision-60 race.
- Make seed suffix handling strict and preserve exact seed bytes.
- Independently validate projected scenarios, hashes, first-three diagnostics, marginals, team sums, and safe-copy boundaries.
- Run the 22 required probes and the 15-command acceptance ledger.
