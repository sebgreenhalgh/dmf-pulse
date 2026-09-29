# D6 offline acceptance

## Scalability and exactness

- Repository-owned L6-shaped workload: 13 retained root incoming players, seven
  terminal incoming players, exact root upper 8,386, effective action/state cap
  17,000, 12,887 reachable non-root states and 520,651 complete primary legal
  actions after reuse.
- Immutable parent at 524,288: typed cumulative-action failure at first synthetic
  crossing 524,289, no incumbent. Immutable parent completes at 786,432 with
  559,313 total actions including the redundant baseline replay.
- Proposed policy: success at 520,651 actions, 12,887 non-root state expansions,
  520,651 policy candidates and 12,888 peak Pareto candidates. The 786,432
  cumulative and policy caps leave 265,781 actions/candidates (51.0%) headroom.
- Progressive successful probes at 524,288, 786,432, 1,048,576, 1,572,864 and
  2,097,152 all retain decision SHA
  `33536fdcf68d72ca252f1997b86989f7b96078c5a070363c17502ba7c664a044`.
- Parent-complete and proposed recommendation, no-transfer baseline, root
  counterfactual and transfer-count frontier are exactly equal. The generic
  enumerator retains its existing independently authenticated baseline replay and
  frozen result hashes.
- Five accepted 001P cases A/B/C/D/E: all `PASS` through the real offline pipeline.

## Test populations

- D6 risk-focused optimisation/private diagnostic population: 341 passed in
  1,172.37 seconds.
- Complete private-v1 plus ordinary one-command ingestion population: 651 passed
  in 3,840.05 seconds.
- Complete public optimisation unit/property/contract/golden population plus
  football-events and Stage-9 shadow regressions: 695 passed in 718.05 seconds.
- Post-review remediation population, including every Stage-11 golden and the
  preferred-but-ineligible generic fallback: 57 passed in 92.87 seconds.
- Final typed-boundary assurance after moving selection behind validation: 64
  passed in 79.15 seconds; Ruff and strict mypy passed again.
- An initial public population exposed generic-path result-hash drift. No golden
  was updated: reuse was narrowed to the shared actual fast-path predicate, the
  independent reviewer re-reviewed it, and the complete 695-test population then
  passed.
- Mandatory full-repository branch coverage, performance and PostgreSQL suites are
  supplied by exact-SHA CI; no coverage floor or exclusion changed.

## Quality and packaging

- `uv sync --all-groups --frozen`: PASS, 40 packages checked.
- `uv run ruff format --check .`: PASS, 911 files formatted.
- `uv run ruff check .`: PASS.
- `uv run mypy src/dmf_pulse`: PASS, 313 source files.
- wheel and source distribution: PASS.
- clean external runtime-only installed-wheel verification: PASS; L1-L6 consumed,
  no current authority, provider calls zero, mutable-source and wrong-purpose
  requests rejected.
- `dmf specs validate`: PASS, 94 decisions / 22 documents / 19 scopes.
- `dmf --version`: `0.2.0`; doctor: `HEALTHY`; test configuration validation and
  sanitized JSON display: PASS.
- first-party secret scan: PASS, zero findings.
- `git diff --check`: PASS.
- canonical manifest, repository validation and capped review pack are generated
  after this ledger is sealed.

## Review and boundaries

- Fresh independent review found and caused remediation of one material P2: the
  first reuse gate followed preference rather than actual enumerator selection.
  The service and solver now share one exact selector and the reviewer confirmed
  no unresolved P0, P1 or material P2.
- Final independent verdict:
  `CLEAR_FOR_TEAM_STRENGTH_L7_REAUTHORIZATION_DECISION`.
- Official FPL requests: 0. The Odds API requests: 0. Live OpenFootball requests:
  0. Credential inspection: none. Historical private L6 rows reconstructed: none.
- L1-L6 are permanently consumed. No L7 authority exists. Team strength remains
  `SHADOW_NOT_MODEL_INPUT`; production activation is false.
