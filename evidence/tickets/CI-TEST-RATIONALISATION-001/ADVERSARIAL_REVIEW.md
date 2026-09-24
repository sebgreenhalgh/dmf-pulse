# Adversarial final review

## Review basis and independence boundary

This review was performed from the clean detached verification worktree at the
code-bearing checkpoint `d84aad776e0b43245771e448c23856f1b77b7c78`, using the
Phase-1 and Phase-2 exact-SHA CI artifacts rather than the implementation
worktree's transient state. It is independent of that mutable worktree and its
local database state. It was performed by the same primary agent; no claim of a
separate human or second-model reviewer is made.

Evidence reviewed included the complete 5,304-node inventory, normalized-AST
duplicate scan, removal mapping, targeted counterfactual, focused 29-test run,
fast-suite run, frozen-surface diff, clean-worktree repository checks, and green
exact-SHA workflow run `35950179886`.

## Questions and findings

1. **Were tests deleted because they were annoying rather than redundant?** No.
   One exact normalized-AST duplicate and one exact duplicate parameter state
   were removed. Runtime and age were not removal criteria.
2. **Could a previously caught production bug now escape?** No identified case.
   The retained optimiser successor failed under the targeted error-code
   counterfactual, and every distinct authority-invalid state remains present.
3. **Are critical invariants protected by a strong test?** Yes. The removed
   optimiser case is owned by the later contract gate; the authority cases remain
   in the fail-closed L2 module. The complete canonical population remains blocking.
4. **Did parameterisation reduce cases?** It removed only the second copy of the
   `wrong/wrong` case. Wrong L1, L2, L3, L4 and all-wrong states remain.
5. **Did shared fixtures introduce order dependence?** No new shared fixture was
   retained. The low-yield D3 experiment was reverted.
6. **Do affected tests pass alone and together?** Yes. The retained successor,
   consolidated authority module, and cadence contract tests passed in the
   focused 29-test run; the full population passed in CI.
7. **Did marker changes remove tests from normal CI?** No marker or workflow file
   changed. Full remains exactly 5,300 non-performance plus 4 performance tests.
8. **Are all baseline tests accounted for?** Yes: 5,302 retained nodes plus two
   redundant removals, offset by two cadence-regression nodes, yields 5,304.
9. **Was historical provenance confused with redundancy?** No. Three same-body
   historical clusters were retained because their named parameter groups express
   distinct semantics. Historical GCS-008 naming debt was documented, not deleted.
10. **Did headline coverage hide lost semantic protection?** No. Coverage remains
    92%. The exact branch-artifact delta is two hits out of 15,522, confined to
    unrelated stale-write reuse guards whose execution depends on the winner of a
    permitted ingestion concurrency race. No ingestion source or test changed.
11. **Were time-travel, rights, security and fail-closed safeguards preserved?**
    Yes. They remain in the complete blocking collection; frozen-surface and secret
    checks passed.
12. **Did live/provider access occur?** No. Profiling, tests and CI used repository
    fixtures/synthetic inputs and the test database.
13. **Did any production numerical path change?** No production file changed from
    the exact Phase-1 parent.
14. **Is the fast suite useful?** Yes: 2,117 tests passed in 217.77 seconds
    (3m37.77s), with a recorded node-ID hash and explicit exclusions.
15. **Is full acceptance materially cheaper or simpler?** It is simpler to invoke
    through one documented command, but not cheaper in the measured CI run. Wall
    clock changed from 24m59s to 31m33s and aggregate shard-job time from 13,526s
    to 14,018s. The unchanged tests and 3.6% aggregate increase indicate execution
    variance; the larger wall-clock change exposes the already documented static
    scheduler imbalance. It is not represented as a Phase-2 saving.

## Coverage-delta investigation

The baseline and candidate combined `coverage.json` artifacts were compared by
executed line and branch arc. The only losses were lines 2190-2191 and 2264-2265,
with arcs 2189->2190 and 2263->2264, in
`src/dmf_pulse/ingestion/fpl/persistence.py`. These are the two older-capture
short-circuit paths in fixture revision and assignment persistence. The relevant
production and ingestion-test files are byte-identical across the compared SHAs.
The difference is therefore an incidental race-order hit, not a removed oracle or
state. The exact branch proof remains recorded rather than rounded away.

## Verdict

No P0, P1, or material P2 correctness/security finding was identified. The
review records two non-blocking limitations: full canonical CI was not cheaper in
this run, and organizational reviewer independence was unavailable. Static shard
weights, generic GCS-008 naming, and deterministic timing-history work remain
explicit future debt. No PR, merge, tag, live call, or credential access occurred.
