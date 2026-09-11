# R7 command evidence and resume record

## Baseline verification

- Read complete user R7 attachment and root AGENTS.md.
- `git rev-parse readiness/PRIVATE-V1-ONE-COMMAND-001N-R6-bounded-horizon-candidate-search`
  returned `5878a39448456df0d07d58823e6dfa7c8e574715`.
- `gh run view 34503653544 --json headSha,status,conclusion,jobs` confirmed
  that same SHA, completed/success and all 12 jobs successful.
- Created isolated R7 worktree/branch at that immutable SHA. Root availability
  worktree edits remain untouched.
- Read authority manifest A10/A11/B2 scope mapping; DMFP-20 OPT-001..006
  (OPT-006 remains PROVISIONAL), DMFP-12 sections 25/26/38. Accepted exact tactics,
  cohort sale proceeds, nonanticipativity and non-dominated alternatives control.
- Parent `multi_gameweek_solver.py` action enumeration resets combinations per
  state; its 17,000 guard is not cumulative. Parent `stage10_adapter.py`
  evaluate_many loops unique squads through ExactTacticalNodeKernel.optimise.

## Resume

Status: profiling harness under construction; NO acceleration acceptance yet.
Next: frozen live-shape search and direct overlapping-squad wall/CPU profiles,
then select exact algorithmic changes based on evidence.
