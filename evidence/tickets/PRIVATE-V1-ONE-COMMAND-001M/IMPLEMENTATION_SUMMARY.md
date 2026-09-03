# PRIVATE-V1-ONE-COMMAND-001M implementation summary

- Added an immutable, hash-bound Stage-11 `TransferCountFrontier`, selected from the existing
  evaluated policy candidates by exact root transfer count, current Stage-10 points after compiled
  hits, and the existing canonical tie key.
- Added typed private frontier points with transfers, resulting squad, tactics, formation, exact
  bank, paired gain distribution versus hold, compiled FT state before/immediately after/at the
  next deadline, and action/scenario/projection/optimiser lineage.
- Reused the accepted paired comparator semantics on identical Stage-9 scenario identities and
  weights. No independent quantile subtraction, resampling or projection regeneration occurs.
- Added a pure shared renderer for synthetic and live-shaped reports. It labels adjacent values as
  frontier deltas, distinguishes strict extensions from non-nested plans, and does not claim a
  causal value for a particular transfer.
- Preserved legacy result and decision hash verification when the optional additive frontier is
  absent; new successful artifacts bind the frontier through their containing semantic hashes.
- Preserved candidate/action scope, Stage-10 tactics, recommendation selection, scoring, chips,
  providers and rights. No future FT value or rolling multi-Gameweek optimisation was introduced.

## Files changed

- Optimisation contracts and selection:
  `multi_gameweek_models.py`, `multi_gameweek_solver.py`, `multi_gameweek_service.py`.
- Private structured contract and report:
  `private_v1/models.py`, `private_v1/service.py`, `private_v1/reporting.py`,
  `private_v1/one_command.py`, `private_v1/__init__.py`.
- Tests and governed fixtures:
  `test_transfer_count_frontier.py`, `test_transfer_frontier.py`, `test_one_command.py`, and the
  Stage-11 adversarial successful-result hashes.
- Scope and evidence: this ticket's YAML, acceptance contract, `PLANS.md`, command ledger,
  benchmark, coverage JSON, result and final self-review.

No dependency, configuration, rules, provider, persistence, live-transport or CI workflow file
changed.
