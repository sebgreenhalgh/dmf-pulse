# Quality, cleanup and feedback continuation

Research branch: `research/DMF-MODEL-QUALITY-001`. The original audit at
`12fa98b977b99b75ac8dc37754701ee99dcfea9b` remains the starting checkpoint.
This continuation changes test automation and owned fixtures, not the numerical
champion, provider routes, installed operator, rules, trust or live databases.
No live FPL/Odds request or credit was used. No PR or merge was created.

## Verified findings

The baseline's [CI run 42321646466](https://github.com/sebgreenhalgh/dmf-pulse/actions/runs/42321646466)
completed successfully: all 20 required jobs passed, including merged coverage,
strict typing, PostgreSQL, performance and installed wheels. This accepts that
baseline only. Every continuation source checkpoint needs its own FULL result.

The copied installed ACCEL003 harness used a selector that returned immediately
despite a positive wait timeout. Its socket-free loop therefore busy-spun while
waiting for executor work. An 80ms executor experiment observed 133,099 selector
calls and 0.125s CPU before, versus 10 calls and CPU below the timer's resolution
after adding an event-backed blocking wait/wakeup. This is a harness fix; the
installed wheel and application engine are unchanged.

The instrumented original complete acceptance failed after 832.54s: both full
horizon parity cases passed, but cancellation polling exceeded its existing
phase limit and reached an uninitialized local. It was **not** a timeout. The
corrected complete run passed in 379.05s under the unchanged 900s bound. Horizon
1 fell from 257.34s to 86.47s; horizon 3 from 402.84s to 227.70s. These are serial
runs on this Windows host, not a universal throughput guarantee. All original
121-catalogue/120-projected, full-result numerical comparisons, exclusions,
cancellation phases, actual worker/ASGI/CLI and network guards remain.
Earlier 900s failures remain in the original sealed evidence.

The first diagnostic supervisor accidentally observed its source digest at
completion. The original receipt is preserved. A supplemental receipt explicitly
records a retrospective replay of the exact timing instrumentation over the
immutable baseline Git blob; the result equals the preserved executed driver.
The corrected run captured its source digest before launch. Neither observation
is relabelled as a prelaunch measurement of the failed run.

## Four feedback tiers

Use Python 3.13, the frozen uv environment and explicit affected test paths.
Each run creates a fresh ignored `review_pack/dev-checks/<tier>-<id>` containing
commands, source identity, raw streams, durations, hashes and JUnit. No artifacts
are acceptance caches. A changed source, interrupted command, timeout, failure
or incomplete run cannot receive a pass receipt.

| Tier | Example | Meaning |
| --- | --- | --- |
| FAST | `uv run --frozen python scripts/dev_checks.py fast --target tests/unit/scripts/test_dev_checks.py` | Format/lint, explicit targeted types where supplied, affected unit tests and essential security/rights/import smokes; no coverage instrumentation. |
| FOCUSED | `uv run --frozen python scripts/dev_checks.py focused --target tests/unit/operation/test_analysis_quality.py --target tests/unit/operation/test_analysis_quality_views.py --target tests/unit/operation/test_analysis_store.py --coverage-module dmf_pulse.operation.analysis_quality --coverage-module dmf_pulse.operation.analysis_store --coverage-module dmf_pulse.operation.analysis_cli` | All affected subsystem modules plus smokes, with explicitly scoped branch coverage. Its zero global floor avoids misrepresenting partial coverage as a repository gate. |
| INTEGRATION | `uv run --frozen python scripts/dev_checks.py integration --target tests/integration/operation/test_analysis_fixture_parity.py --target tests/unit/scripts --target tests/unit/operation/test_analysis_fixture_integrity.py` | Fresh complete owned engine execution and every-field equality for the frozen analytical input, plus affected tooling and smokes. Add applicable database/browser integration targets for those changes. |
| FULL | `uv run --frozen python scripts/dev_checks.py full --ci-run <exact-push-run-id>` | Requires clean unchanged HEAD, the actual authoritative ci.yml workflow ID, a successful push event for that HEAD, and all 20 exact mandatory jobs successful. It verifies full authoritative CI; it does not promote or sign a release. |

When package source changes, partial checks conservatively type-check all
`src/dmf_pulse` unless explicit source targets were provided. Tests/automation
only report typing `NOT_REQUESTED`. An earlier Windows Application Control block
of mypy/librt remains historical failed evidence. The continuation's literal
strict typing run passed in 45.59s without changing or replacing the checker.
Any future host-policy failure must remain blocked; do not bypass host policy.

Owned unit fixture loading removes duplicate full engine setup from analytical
store/report tests. It retains all 121 rows, 120 projected players and complete
presentation; every consumer gets a fresh validated model. Raw bytes, semantic
hash, ownership and population are pinned. The integration test regenerates the
complete engine and requires **every field and the semantic hash** to match.
No custody/hash exclusions were added. Any package identity change requires
explicit reviewed fixture regeneration; do not silently refresh pins. The first
old-QA fixture failed strict build identity equality and was replaced with a
complete current-source regeneration. Failed attempts remain recorded.

The initial accelerated focused run passed 131 tests in 42.72s command time,
39.15s pytest time, versus 64 tests in 474.49s/471.71s previously. The added tests
include essential smokes; coverage was enabled in both. This supports a greater
than 90% reduction in this local edit loop. It is not a comparison of the entire
suite or a claim that model execution became 90% faster.

## CI scheduling

All 16 successful baseline shard logs supplied 573 approximate module-fragment
elapsed observations. Progress timestamps include setup/output/scheduling effects,
so the manifest labels them **estimated**, not measured pytest node durations.
The existing validated LPT scheduler and 16-shard architecture remain intact.
No dependency or action, workflow permission, selection marker, timeout, seed,
scenario count, coverage threshold or acceptance job changed. Frozen dependency
sync took about one second in the baseline; extra dependency caching would not
address the dominant cost.

The exact original 8,526-node multiset and digest remain once each. The three
function-isolated full 256-scenario standing-pipeline cases can occupy different
shards; they own their transports, manager state and monkeypatches. D4's expensive
module fixtures stay together. Updated estimated loads are 2,551s longest and
about 1,972s elsewhere, versus an observed baseline maximum 5,092s. These are
different kinds of measurements: no measured CI speedup is claimed until the
new exact-SHA run completes. Normal collection additionally includes new tests.

## Repository and local cleanup

Paginated inventory found 125 remote branches, 22 historical PRs, zero open PRs,
one open issue, one tag and one release. Fifteen obsolete non-worktree branch
tips were ancestors of **all three** surviving main/launch/research roots. An
ordinary atomic push with a pinned exact deletion-set/old-tip pre-push guard
removed one pilot then fourteen branches. Before/after reconciliation verified
110 remaining refs unchanged, with tags/releases preserved. Native disposable
Git experiments proved stale-tip refusal and server-rejection atomicity. No
force option or history rewrite was used. The static acceptance branch remains
on HOLD because root PowerShell automation references it.

[Issue 14](https://github.com/sebgreenhalgh/dmf-pulse/issues/14) was closed as
completed only after its workflow-removal criterion and all comments were read;
the removal is in preserved ancestor `17b6aa576459c652e14015dcfd7b7cf0bffd6f9d`.
Its body and 84 comments remain. No open PR or issue remains at that check.

The local inventory covers 105 registered worktrees and 37,609,285,121 listed
logical bytes. It excludes 19 protected paths and reports 441 metadata access
errors; this is a lower bound, not a complete disk or allocated-block measure.
Eight dirty worktrees and their unique work remain protected. The launch data
depends on PostgreSQL executables under `review_pack/ACCEL-002`; age/name alone
would have misclassified this live dependency. Both live clusters, the signed
operator, permanent SQLite, original audit custody and active research remain.
No worktree has been force removed or manually moved.

Whole environment/site-packages proposals are **HOLD**: mutable installed RECORDs
are insufficient proof against a locked wheel, and shared hardlinks make broad
ACL resets unsafe. The bounded alternative proves only flat CPython 3.13 caches
with one link per file, current magic/header, exact complete compile/marshal body
reproduction from sibling sources that remain in place, no reparse points, and
fresh identity/membership checks. No source or bytecode is executed or loaded.
The first 120 caches cover 4,264 files and 268,862,105 logical bytes. Another 7,256
discovered caches remain unproven/HOLD. Actual moves require reviewed native
PowerShell containment, process/task/service/CWD-lock and rollback safeguards.
Fresh Git status excluded three caches spanning two unreadable checkouts; the
reviewed execution subset is 117 caches / 262,151,451 bytes. The first preflight
stopped after 73 read-only checks on an exited-process metadata race. The next
stopped before any candidate at the PowerShell Set-Acl audit-privilege boundary.
Both receipts remain; the narrower owner/DACL .NET API was tested on an isolated
new directory. No stopped preflight is counted as an archived cache.

Archive destination:
`C:\Users\sebgr\Documents\DMF_PULSE_ARCHIVE_PENDING_OWNER_DELETION`.
Owner/SYSTEM-only manifests, per-file proofs and original ACL/restore receipts
stay in durable private custody outside the deletion archive. A same-volume move
frees **zero bytes**. Only the owner may delete the archive; recoverable logical
file bytes are not an NTFS allocated-space guarantee.

## Checkpoint and remaining programme

This is an engineering checkpoint. Mathematical MQ-000 challengers, MQ-002 exact
match-time membership and MQ-003 prospective custody remain next in the accepted
order. No accuracy gain, real-label evaluation or production activation is
claimed. Unqualified rights, missing membership, late freeze or absent finalized
labels remain explicit blockers; no new data authority is inferred.

Continuation source, review and gate receipts live in
`evidence/tickets/DMF-MODEL-QUALITY-001/resume/`. The original sealed evidence is
historical and is not overwritten. A final exact-commit FULL CI result, archive
outcome and independent review must accompany any completed handoff.

Local continuation gates passed frozen sync, formatting, lint, strict typing,
fresh integration (138.99s), focused coverage (45.86s), inherited regressions
(180.44s), SQL stress (7.28s) and build (16.69s). Repository validation then
correctly rejected the stale sealed baseline current manifest. The validator
now prefers a separately captured continuation manifest; regression tests verify
old bytes remain unchanged, new source is checked, and malformed/stale continuation
manifests fail closed. Secret/repository/final-diff results follow in gate receipts.
