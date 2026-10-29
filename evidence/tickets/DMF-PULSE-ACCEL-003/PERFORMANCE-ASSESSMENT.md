# ACCEL-003 independent D4 performance assessment

Complete A–D integration and the unchanged acceptance gates first. A bounded
profiling follow-up is justified; a D4 split, extra shards or new cache is not
supported by the retained measurements. This review changes no test, source,
workflow, timeout, coverage floor or scheduling manifest and runs no benchmark.

## Reauthenticated historical measurements

The retained GitHub Actions run **40886756682** binds the exact ACCEL-002 parent
`8b74d5f3dc41eb1246ae82388ec6aab3743241b8`, with all twenty jobs successful.
The publication receipt's raw metadata, coverage-plan archive/member digests and
independently reviewed D4 raw-log digest were recomputed locally. The retained
CI-LATEST jobs equal the authenticated raw-metadata jobs. No network request was
needed. These are historical Ubuntu/branch-coverage results, not ACCEL-003 timings.

| Observation | Seconds | Meaning |
| --- | ---: | --- |
| D4 pytest total | 2,515.64 | Actual `112 passed` total for the sole-module session |
| D4 pytest workflow step | 2,519 | Whole step, including pytest startup/exit |
| D4 complete runner job | 2,546 | Includes checkout, sync, database and transport |
| Next slowest shard 11 pytest step | 2,395 | Separate 254-node population |
| Earlier D4 progress-log interval | 2,551.107 | Estimate from run 40831728997; not a node/setup measurement |

The exact parent plan already places all **112 D4 nodes alone on shard 0**.
The D4 and shard-11 jobs both started at 13:58:44Z and completed at 14:41:10Z
and 14:39:02Z respectively. Holding every other historical start/finish fixed,
even removing D4 entirely could advance that coverage barrier by at most
**128 seconds**. This is a counterfactual bound for that observed schedule,
not a future speedup prediction. Shard 11 also deserves profiling before a
broad scheduling change. More shards cannot divide the currently intact D4 group.

The 112-node D4 source is byte-identical to the parent and its earlier independent
review. The older 6,127-node placement simulation and final 6,138-node covered
collection are distinct artifacts; their populations are not conflated here.

## Static setup and reuse architecture

`tests/unit/private_v1/test_team_strength_d4_rolling_diagnostics.py:42` defines
`captured_rolling_pipeline` with module scope. It runs one complete real rolling
pipeline and captures three projections/assemblies plus two optimizer results.
Twenty-two parametrized test nodes consume it. Their per-test patches create
fresh iterators over captured values and preserve injected failure handling.

The module's line 89 defines a separate module-scoped
`captured_full_seam_pipeline`. It runs the complete owned offline seam through
the baseline world to BUILD_STAGE11_WORK and captures automatic rolling minutes
as well as rolling outputs. Twenty-three nodes consume this fixture. Each still
calls `_full_seam` at
`tests/unit/private_v1/test_team_strength_d3_seam.py:55`: owned source-body and
transport construction, authority/preparation/callback execution and failure
localization run per node; only selected model stages are replayed from captures.

One additional full-seam failure and one Stage-8/9 localization test execute
without those captures. The remaining 65 nodes check closed diagnostics,
allowlists, canary redaction and source/trace contracts. These counts come from
the authenticated parent plan and static fixture dependencies, not measured cost
shares. No retained per-node setup/call/teardown timing distinguishes the two
captures from repeated preparation. An earlier, different D3 setup-reuse
experiment measured 412.76 versus 411.57 seconds and was reverted for no material
benefit; that result does not establish a D4 optimization.

Global function-scoped home/network isolation and fresh monkeypatch lifetimes
must remain. PostgreSQL cleanup applies to marked database tests, not this
unit-marked D4 population. The known two captures already amortize their work
inside a module/process. Naive node distribution can pay either capture repeatedly
on multiple runners, multiplying work and shared-object risks.

## Bounded follow-up

1. Profile the unchanged final source/dependency SHA under branch coverage,
   sequentially recording all 112 nodes' setup/call/teardown and explicit capture
   and preparation boundaries. Profile shard 11 too. Retain host/load, commands,
   failures and complete collection; do not retry selectively.
2. If repeated construction is material, consider sharing only authenticated,
   repository-owned immutable fixture construction. Keep each test's authority,
   custody, prepared callback and distinct injected failure execution. Prove
   nested mutation isolation; a frozen outer model alone is insufficient.
3. Consider capture-dependency groups only after measuring duplicated capture
   cost versus parallel body savings. Keep the 22 rolling consumers and 23
   full-seam consumers together unless stronger evidence supports division.
   Preserve exact nodeids, all failure phases/canaries, the complete branch union
   and an uncaptured real end-to-end seam. No cross-run pickle/provider-body cache.
4. Accept an optimization only after a predeclared bounded paired comparison
   shows meaningful benefit, independent review confirms unchanged numerical and
   failure behavior, and the full unchanged release gates and exact-SHA twenty-job
   CI pass. No timing/coverage threshold, authentication or source right changes.

## Protected-artifact audit status

The companion JSON records the exact reviewed HEAD and working status. Root
integration is still dirty, so this is explicitly an **interim** protected audit;
it must be rerun at the final freeze. At this observation:

- All eleven CP0 protected paths match both current HEAD and working bytes.
- All 157 checked accepted numerical/governance Python files match CP0 hashes.
- The authority manifest matches CP0.
- The original Availability worktree HEAD and status hash match CP0.
- P01 bytes remain
  `e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee`;
  stored semantic SHA remains
  `96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a`.
- P01 was read only as bytes and stored identity: no validator, model or scorer.
  A02/A03 consumption configurations remain unchanged.

CP0 binds the original dirty worktree's HEAD/status, not every pre-existing dirty
file byte. Matching status alone cannot establish byte equality of all those
files. The reviewer made no original-worktree mutation, provider call or credential
read. Exact input hashes and the bounded helper binding correction are retained
in `accel003-performance-assessment.json`; the separate machine audit is
`accel003-protected-audit.json`.
