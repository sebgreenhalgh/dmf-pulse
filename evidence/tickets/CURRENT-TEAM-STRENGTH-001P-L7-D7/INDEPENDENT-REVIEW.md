# D7 independent review

Independent review was completed against immutable parent
`57f578efa168919b63574fa8a3bd4656b6b6d4bf` after final offline acceptance.

## Findings

- P0: none.
- P1: none.
- Material P2: none unresolved.
- The earlier review-pack completeness finding was resolved by including every
  changed implementation/regression file plus final manifest and validation evidence
  within the bounded archive.

## Required determinations

1. PASS — L7 is correctly classified as `POLICY_GENERATION_LIMIT`.
2. PASS — 786,433 is only the first generated-policy crossing.
3. PASS — 783,057 is complete baseline legal-action discovery work.
4. PASS — `max_policy_candidates` previously overloaded generated work and retained
   frontier cardinality.
5. PASS — v2 separates both meanings, validates them fail-closed, and diagnostics
   require exactly one legacy or split representation.
6. PASS — 10 million was only an offline discovery ceiling; governed limits are
   2,097,152 generated / 786,432 retained / 2,097,152 legal actions.
7. PASS — streaming Pareto reduction and transition replay preserve exact objectives,
   deterministic ties, frontiers, alternatives, baselines, counterfactuals and future
   policies. Governed/high-cap decision hashes match in both worlds.
8. PASS — production candidate and transfer scope are unchanged.
9. PASS — complete baseline-like and shifted-shadow-like stresses are covered at
   1,432,370 and 1,432,641 generated policies respectively.
10. PASS — L1 through L7 are permanently consumed.
11. PASS within review scope — code, tests, evidence and review show zero provider
    requests or credential inspection. External actions outside the recorded process
    are inherently not independently provable from repository evidence.
12. PASS — no L8 authority exists; L8 requires separate human authorization.

## Acceptance reviewed

- Optimisation: 334 passed.
- Private rolling/team-strength: 476 passed, 179 deselected.
- Stage 8/9/10 adjacent: 502 passed.
- Final D7: 15 passed.
- Frozen sync, Ruff, strict mypy, build, installed-wheel verification, secret scan,
  repository validator, manifests and `git diff --check`: PASS.
- Capacity evidence semantic SHA256:
  `90e42fd03e32f2eb7e5df6e97c404a41a7784557c6ecaff65674cbda97721e1c`.

## Verdict

`CLEAR_FOR_TEAM_STRENGTH_L8_REAUTHORIZATION_DECISION`

## Post-CI golden review

The first exact-SHA CI run exposed 20 stale Stage-11 golden `result_sha256`
values. Focused review confirmed that exactly those 20 hash fields changed;
request hashes, statuses, backend statuses, error/resource classifications,
actions and objectives remained unchanged. The complete optimisation golden and
exhaustive-oracle population passed 48 tests. The refreshed golden file is included
in the capped review pack. No new P0, P1 or material P2 finding was raised, and the
verdict above remains valid.
