# PRIVATE-V1-ONE-COMMAND-001N implementation summary

- Added an explicit `--horizon-gameweeks 3` path while preserving the one-Gameweek default and
  its existing input/result hash conventions.
- Built current-cutoff Stage-7 inputs once for the current, next, and following official fixture
  sets, then used the accepted Stage-8/9 projection path for each Gameweek. Future fixtures without
  current market evidence use the accepted typed score-prior-only path and expose coverage counts.
- Reused the accepted Stage-11 manager-state, integer bank/price, ownership-spell, compiled FT/hit,
  scenario-tree, action, tactical, and deterministic tie-break machinery. The private topology is
  an explicit deterministic three-node chain with no invented information revelation.
- Added a horizon-valued root transfer-count frontier, paired three-Gameweek comparison against the
  root hold policy, per-Gameweek structured decisions, and a deterministic one-GW-versus-three-GW
  decomposition. Only the root is actionable; both future actions are marked provisional.
- Bound the disabled zero terminal policy after GW+2, current prices held constant, no-chip mode,
  current candidate pruning, and the exact-within-bounded-space limitation into inputs, outputs,
  hashes, warnings, and the human report.
- The maximum transfer count is not introduced as a rolling literal. It is copied from the existing
  governed current candidate policy, which derives it from authenticated FT state, compiled rules,
  and the ticket-bounded search policy, and is then intersected with Stage-11 legality/resource
  bounds at request construction.
- Instrumented current/future Stage 7, each Stage-8/9 projection, each joint scenario assembly,
  action generation, tactical batch evaluation, Stage-11 solving, and report/comparator assembly.

## Files changed

- Optimisation frontier support: `multi_gameweek_models.py`, `multi_gameweek_solver.py`, and
  `multi_gameweek_service.py`.
- Private rolling contracts/orchestration: `private_v1/rolling_models.py`, `private_v1/rolling.py`,
  `private_v1/service.py`, `private_v1/automatic_inputs.py`, `private_v1/one_command.py`, and public
  exports.
- CLI: `cli/pulse.py`.
- Focused Stage-11 golden/oracle and private/CLI contract, service, compatibility, and end-to-end
  tests under `tests/`.
- Governed scope and evidence: this ticket, `PLANS.md`, command ledger, benchmark, coverage report,
  result, manifest, and final self-review.

No dependency, lock, rule, provider transport, persistence, database, workflow, chip, rank, model,
or activation file changed.
