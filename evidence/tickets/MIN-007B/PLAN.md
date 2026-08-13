# MIN-007B implementation plan

- Preserve the exact MIN-007A parent and validated Pack 007B contract.
- Add a minimal typed `dmf_pulse.availability` history model and pure training-dataset builder.
- Enforce explicit START/BENCH/OUT semantics, strict minute bounds, UTC-aware timestamps, duplicate identity rejection, TRAIN-only cutoff eligibility, and canonical row ordering.
- Copy the frozen synthetic history, dataset oracle, summary and negative cases into a ticket-scoped availability fixture manifest without changing their bytes.
- Add focused unit, property and golden tests for the frozen output, shuffle/idempotence invariants, cutoff boundaries, leakage and invalid-label cases.
- Run all literal acceptance commands, record evidence, make the exact bounded commit, and verify a clean worktree.

Non-goals: role modelling, minute PMFs, lineup sampling, persistence/migrations, CLI, evaluation/calibration and any MIN-007A market changes.
