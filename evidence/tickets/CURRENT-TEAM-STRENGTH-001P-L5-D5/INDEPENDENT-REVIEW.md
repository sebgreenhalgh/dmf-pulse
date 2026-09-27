# Independent D5 adversarial review

Parent reviewed: `c348c3c7f2b26ef929dc0d56fa2dc1dbfd356d7e`.

No unresolved P0, P1 or material P2 finding remains.

1. Every Stage-11 resource limit is finitely identifiable: **yes**. All seven
   origins carry a closed `ResourceLimitKind`; `UNKNOWN_RESOURCE_LIMIT` is the
   compatibility identity.
2. Safe counters distinguish the exhausted budget: **yes**. Authenticated
   diagnostics require the finite identity, configured caps, observed per-state
   combinations, state/action/policy/Pareto counts, cumulative legal actions and
   reachable layered states.
3. Exactness is unchanged: **yes**. Limits fail closed without pruning, and an
   incomplete no-transfer baseline cannot produce exact success.
4. Candidate scope is preserved: **yes**. No candidate-selection boundary changed.
5. The cap separation and increase are justified: **yes**. Generated policies and
   cumulative legal transitions are distinct units. The current loader requires the
   new field. The measured workload needs 320,610 actions, fails at 250,036 under
   the legacy 250,000 cap, and completes at 524,288, the smallest power of two above
   measured demand (203,678 actions / 63.5% headroom).
6. Successful decisions are identical: **yes**. The 524,288 and 1,048,576 runs
   produce the same recommendation, baseline, root counterfactual, complete transfer
   frontier and decision semantic SHA
   `f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47`.
7. D1-D4 behavior is preserved: **yes**. The complete prepared one-command seam
   carries the finite resource identity and counters without raw messages.
8. L1-L5 are consumed: **yes**. All five approvals are in the consumed set and no
   current authority exists.
9. No provider was accessed: **yes**. FPL, Odds and live OpenFootball request counts
   are zero; credentials were not inspected.
10. L6 requires separate human authority: **yes**. Current authority is `None` and
    no L6 authority exists.

Independent verification: 372 focused tests passed in 1211.63 seconds. The reviewer
also reconciled the generated capacity artifacts, successful-decision equality,
authority closure, final acceptance records and disclosure-safe diagnostic seam.

The reviewer separately examined the post-review CI remediation. The inherited
R8A static guard now excludes the intentionally changed Stage-11 solver while
retaining the exact Odds parser and client SHA-256 guards. The full horizon-probe
suite passed 84 tests; focused source-identity tests, Ruff and `git diff --check`
also passed. This test-only correction changes no provider boundary, solver
behavior, exactness rule, candidate scope, authority state or activation path.

Verdict:

`CLEAR_FOR_TEAM_STRENGTH_L6_REAUTHORIZATION_DECISION`
