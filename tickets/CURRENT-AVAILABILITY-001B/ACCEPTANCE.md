# CURRENT-AVAILABILITY-001B acceptance contract

This file defines gates. It does not assert that they passed.

## Parent and safety

- The branch is a direct descendant of `99418f3316277f4dae347d80358d5dd5a09655b2`.
- Canonical parent CI run `33401091116` concluded successfully before branch creation.
- The pre-existing dirty CURRENT-AVAILABILITY-001A worktree remains byte-for-byte untouched.
- No real manual judgement, credential, network call, database change, migration, dependency,
  PR, merge, tag, acceptance, or production activation is introduced.

## Contract and mathematics

- Each team supplies canonically ordered explicit scenarios with positive integer counts totaling
  exactly 256 and no probability floats or silent normalization.
- Every expanded scenario contains the identical canonical roster, exactly 11 START players,
  exactly one starting goalkeeper, nine BENCH players including one goalkeeper, and coherent OUT
  membership; START minutes are 1..90 and OUT minutes are zero.
- Player role probabilities and 91-bin minute PMFs are exact empirical frequencies of those 256
  scenarios. Appearance, zero, 60-plus, and expectation identities revalidate exactly.
- Soft evidence cannot create `p_start = 1` or `p_out = 1`; an aligned allowed hard override is
  required. Manual output is grade D with `MANUAL_TRANSIENT_OVERRIDE`.
- Manual team outputs use only `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1`; their dataset hash binds
  the complete canonical input and their model-artifact compatibility hash binds the versioned
  deterministic transformation policy, not a learned model.

## Stage 8 and operator surface

- The closed Stage-7 identity family accepts the existing empirical-Bayes identifier and the
  manual identifier, while rejecting arbitrary strings and preserving fixture/team/time/hash
  gates.
- A fully synthetic test proves manual Stage 7 -> Stage7MinutesContext ->
  ScoreDistributionService.project() without network access.
- `dmf availability manual-override` writes only deterministic immutable artifacts under an
  explicitly named `dmf-private-transient` directory and exits non-zero on malformed input or
  conflicting output.

## Quality

- Focused availability, Stage-7 identity, Stage-8, and CLI tests pass with strong branch coverage.
- Affected inherited availability and football-events regressions pass.
- Frozen sync, formatting, lint, strict typing, diff hygiene, build, installed-wheel smoke,
  repository validation, and secret scanning pass.
- Adversarial review has no unresolved P0, P1, or material P2 finding.
