# DMF Pulse — cleanup, faster feedback and model-quality checkpoint

The continuation removed 15 obsolete remote branches, closed the completed issue,
archived 101 verified bytecode caches and implemented four feedback tiers. The
analytical edit loop fell from 474.49s to 45.38s while adding essential smokes.
MQ000 mathematical challengers, an owned MQ002 membership resolver and an MQ003
bridge to the existing custody service now have 69 passing owned tests.

Production package bytes, signed installation, canonical SQLite, both live
PostgreSQL clusters, source rights and the accepted numerical champion are
unchanged. Zero FPL/Odds calls or credits, FPL account writes, PRs, merges, model
promotion or production migrations occurred. Real research capture remains
blocked by missing qualification and owner protocol intent. Final exact-commit
FULL CI is a separate gate; checkpoint-time status and detached final observations
are recorded explicitly rather than relabelled as an earlier pass.

The **overall local size-reduction target is not achieved**: listed development
bytes grew 698,421,699 during QA/evidence generation despite isolating 226,312,744
cache bytes. No disk-space saving is claimed. Unknown or unsafe material stays
on HOLD; this report does not authorize deleting it.

## A. GitHub and repository navigation

| Item | Before | After verified cleanup |
| --- | ---: | ---: |
| Remote branches, paginated |125|110|
| Open PRs |0|0|
| Historical PR records |22|22|
| Open issues |1|0|
| Tags / releases |1 /1|1 /1|
| GitHub protected flags / rulesets |0 /0|0 /0|
| Registered local worktrees |105|105|

`main`, `launch/GW10-real-pilot`, research and 87 registered-worktree branch names
were preserved. Each deleted tip was an ancestor of **all three** surviving
main/launch/research roots. An ordinary atomic push used a pinned exact deletion
set/old-tip pre-push guard; stale-tip and server-rejection atomicity were proved
in a disposable native Git repository. One pilot and 14 further deletions were
reconciled against all surviving refs. No force option or history rewrite was used.
Exact names/tips are in [remote-cleanup.json](../../evidence/tickets/DMF-MODEL-QUALITY-001/resume/remote-cleanup.json).

The static-acceptance branch remains HOLD because `ACCEPTANCE_COMMANDS.ps1:5`
references it. Unique/unreviewed tips and branches referenced by worktrees remain.
The complete 125-row classification is preserved privately and in durable recovery.
[Issue 14](https://github.com/sebgreenhalgh/dmf-pulse/issues/14) was closed only after
checking its workflow-removal criterion and all comments; ancestor
`17b6aa576459c652e14015dcfd7b7cf0bffd6f9d` supplies the removal. Its body and 84
comments remain. No PR backlog was invented.

Active research checkout is `review_pack/MODEL-QUALITY-001` on
`research/DMF-MODEL-QUALITY-001`; required launch checkout is `review_pack/GW10-LAUNCH`.
The original dirty availability checkout remains untouched. This report and the
existing audit/roadmap are linked from the [operations index](README.md).

## B. Local archive, protected assets and storage

**Owner deletion archive:**
`C:\Users\sebgr\Documents\DMF_PULSE_ARCHIVE_PENDING_OWNER_DELETION`

Only 101 flat, proven recreatable CPython 3.13 cache directories were moved:
3,590 files / 226,312,744 logical bytes. Including the owner README, the measured
archive has 3,591 files / 226,313,018 bytes. Every cache file has one link, current
magic/header, and an exact complete compile/marshal body reproduced from sibling
source that remains in place. No source or cached code was executed/loaded for
that proof. Original/destination paths, commits, counts, hashes, reasons and
restore references are in [local-cleanup.json](../../evidence/tickets/DMF-MODEL-QUALITY-001/resume/local-cleanup.json).

Native preflight checked exact sources/targets, ancestors/device, clean unchanged
checkout, process command references, services/tasks and directory locks. Fresh
proofs, identity checks and owner checks preceded each move. All final bytes,
file IDs, timestamps, link counts, retained-source hashes and 3,691 cache directory/
file owner+SYSTEM protected ACLs passed independent verification. All 19 held
caches remain in place: three from unreadable checkouts and 16 with mismatched
owners. Another 7,256 discovered caches remain unproven/HOLD.

Whole environments remain HOLD. Installed RECORDs do not independently authenticate
the locked wheel, and shared hardlinks make broad ACL resets unsafe. No worktree,
package source, native dependency or old evidence tree was bulk-moved or removed.
The preliminary whole-environment proposal is superseded, not deletion approval.

The first preflight stopped on an exited-process metadata race; another stopped
on PowerShell Set-Acl's audit privilege. The first pilot moved one cache but its
directory-first ACL update removed inherited child ACEs. The stop, original
journal and exact bytes were preserved. A disposable-proven, owner-preserving
DACL-only repair restored all 38 files; independent verification passed. The final
executor protects files first, changes directories last and preserves owners.
All failed and repaired receipts remain; no incomplete pilot was counted as pass.

**Durable evidence/rollback folder — keep this:**
`C:\Users\sebgr\Documents\DMF_PULSE_CLEANUP_RECOVERY_20261107`

It is outside both checkout and deletion archive. All 266 content-only copies have
verified independent inodes, sizes and hashes, with owner/SYSTEM-only access.
`RESTORE.md` contains 101 exact source/destination commands, refuses recreated
source paths and explains original Access-section SDDL restoration. Historical
proposals remain evidence only; only the executed 101-cache set is deletion-safe.

| Metadata inventory | Before | After snapshot |
| --- | ---: | ---: |
| Listed logical file bytes |37,609,285,121|38,307,706,820|
| Protected/reparse exclusions |19|19|
| Metadata access errors |441|446|
| Registered worktrees / dirty |105 /8|105 /8|

These are lower bounds over the recorded development scope, not complete allocated
disk usage. New QA outputs and retained evidence contributed to growth; snapshots
are not a causal attribution of every byte. The signed installation and live
PostgreSQL contents are not included in a recursive disk estimate. At least
5,372,122,659 counted metadata bytes remain in protected launch/ACCEL002 roots,
excluding their pruned runtime/data paths and other protected locations.

Both live PostgreSQL data roots are under GW10-LAUNCH; their executable dependency
is under `review_pack/ACCEL-002/review_pack/postgres-runtime/pgsql/bin`. The cluster
inside `standing-operation-001/owned-postgres-002/data` is live despite its name.
Neither data tree was recursively scanned/hashed/copied. The signed operator,
canonical SQLite, original audit custody, P01, trust, dirty worktrees and active
research were preserved. Initial/final root and launch HEAD/status metadata agree.

**Same-volume space freed: 0 bytes.** Owner deletion may recover approximately
226,312,744 logical cache file bytes; allocated NTFS blocks/compression/directory
overhead are not measured. No other HOLD directory is approved for deletion.

## C. Faster testing, evidence and remaining bottlenecks

| Tier/check | Before | Verified after |
| --- | --- | --- |
| FAST | No equivalent formal tier |136 tests,10.61s pytest command +0.65s format/lint; no coverage |
| FOCUSED analytical loop |64 tests,474.49s command /471.71s pytest |131 tests,45.38s final tier command; branch coverage retained |
| INTEGRATION | No equivalent formal tier |514 tests,132.53s final tier command; fresh full engine, scripts and smokes |
| Browser current-mode + loop regressions | No comparable Windows capture; old Linux module bound 1481.80s is a different host/coverage scope |63 tests,352.46s; both complete horizons retained |
| Installed complete ACCEL003 probe |832.54s failed; earlier 900s timeouts preserved |379.05s PASS with unchanged 900s bound and wheel |
| FULL |20 jobs PASS at 12fa; 6,226s job chain; slowest shard 5,125s |Engineering 466: all 20 jobs passed in 3,739s; later final-SHA result independently required |

The focused reduction exceeds 90% for this measured edit loop, with more smokes
and coverage in both commands. Other rows differ in scope/host and do not support
an invented percentage. Dependencies were warm/frozen; CI sync was about 1s and
was not the dominant bottleneck. No new dependencies/actions or acceptance cache
were added. Slow numerical simulation still dominates complete acceptance.

The copied socket-free selector returned immediately despite positive timeout,
busy-spinning while executor work waited for the GIL. An 80ms executor probe showed
133,099 selects / 0.125s CPU before versus 10 selects / CPU below timer resolution
after event-backed wait/wakeup. Both current-browser tests and installed proof
now reuse the corrected loop. Original horizons 1/3, 121 catalogue / 120 projected,
exact result comparisons, cancellation, real worker, ASGI/CLI and network guards
remain. No fixture, tolerance, scenario or 900s limit was weakened.

The original instrumented run passed both numerical cases but failed cancellation
polling. Same-case horizon times fell 257.34→86.47s and 402.84→227.70s. It was a
failed full run, not a completed baseline PASS. Its supervisor observed the source
digest too late; the untouched receipt has a transparent supplemental retrospective
reconstruction equalling the preserved executed driver. The corrected run measured
its source before launch. Neither observation is misrepresented.

Analytical unit tests now load an exact owned full snapshot with fresh independent
models. Strict raw/semantic/provenance/population pins apply. The integration
test regenerates the complete engine and requires **every field and semantic
hash** to match, with no custody exclusions. An older QA fixture failed build
identity equality and was regenerated; failed attempts remain. Package changes
must trigger explicit reviewed regeneration rather than silent pin refresh.

The existing 16-shard scheduler uses 573 honestly labelled approximate progress-log
observations. Original 8,526 tests remain exactly once with identical collection
digest; new tests are collected normally too. Three independent standing-pipeline
cases can occupy separate shards; D4's expensive shared module fixtures stay
together. Estimated loads were 2,551s maximum / ~1,972s elsewhere, not measured
speedups. The engineering run passed all 20 jobs: observed job chain 6,226→3,739s (39.95% reduction), and slowest shard 5,125→2,839s (44.60%). Runner variation and the combined changes limit causal attribution. The later source commit still requires its own FULL result. No workflow permission,
coverage floor, job, seed, scenario count or acceptance timeout changed.

Run `uv run --frozen python scripts/dev_checks.py` with `fast`, `focused` or
`integration` plus explicit `--target` paths. Essential rights/security/import
smokes are always added. Source changes, interruptions, failed startup and timeouts
cannot receive pass receipts. Explicit scoped coverage is partial feedback; it
does not satisfy the global release floor. Core source changes conservatively
type-check all `src/dmf_pulse` unless explicit applicable type targets are supplied.

FULL uses `full --ci-run <id>` from clean unchanged HEAD and authenticates the
actual ci.yml workflow ID/path, exact push SHA and all 20 mandatory successful
jobs. PR merge checkouts, omissions/skips and local PASS assertions are refused.
Production promotion/signing remains separate.

## D. Model-quality continuation

| Research slice | Implemented and tested | Boundary |
| --- | --- | --- |
| MQ000 |31 tests: exact Fraction arithmetic, declared fixed-grid ordinal RPS, zero-key/permutation/propriety properties; inclusive PMF quantiles accept valid upper/lower rare tails |Accepted Stage 12 scores and Stage 11 optimizer validators unchanged; new versions opt-in only |
| MQ002 |17 tests: exact historical membership, transfers, doubles, blank/missing distinctions, postponement/rearrangement, ambiguity, cutoff, zero-minute starts; actual unchanged champion counterexample |Owned inputs only; no real source/training authority or production adapter inferred |
| MQ003 |21 tests: complete original player×model population, existing adapter and source/intent/population gates, native custody calls, final-label append, partial/unknown outcomes and interruptions |No warehouse reconstruction, real ledger connection or fabricated historical freeze; native future deployment needs applicable qualification/acceptance |

The MQ002 same-input owned counterexample changes one fixture/team assignment
while retaining observed 60 minutes; no prediction or accuracy gain is inferred.
MQ003 reuses server-clock native transactions and Stage 12 evaluation. A batch is
not atomic: completed hashes and the uncertain attempted cell are preserved on
failure; reconcile before retry. Missing labels remain missing, revisions stay
explicit and previous vintages are not erased.

`model_quality_math.py --owned-demonstration` shows invariant 1/2 RPS and a valid
mean 1 above p90=0. `model_quality_custody.py --readiness` reports the actual empty
real registry: 0 qualified sources, 0 accepted intents, nonzero exit and no DB/provider
access. The operational Stage 9 snapshot adapter remains synthetic-only. Real
membership and original-output retention require exact source/purpose/retention
qualification, budget and protocol approval. Matched finalized evaluation sample
remains 0 in this permitted audit; no confidence grade, calibration or predictive
skill upgrade is claimed. See the three bounded contracts in the ticket.

## E. Database and protected release status

Canonical warehouse SHA256 remains
`bdbf46c917819438e7d4a8033b087a9cb5a583930bb005d13692c5485ef9eaa7`;
active-release manifest remains
`bd28d6827cb7c1dbb244225996beff6a726250072ac18836d4c72270b8ba4132`.
The rebuilt research wheel is exactly the earlier 1,987,239-byte wheel
`654d1d5638a61b7feca916c4e889cb0c920a38b6f21989e75e6864e14d36075e`.
No redundant installed run was needed for identical bytes; final hosted gates
remain required. The earlier local type-checker policy failure is retained, and
the continuation's literal strict typing passed without replacing the checker.

Research v2 quality diagnostics, identity guards and three derived views remain.
Canonical live data stays v1. The signed v1 reader rejects schema 2; no v2 production
migration is authorized until compatible deployment/rollback acceptance exists.
Original model audit, 19-capability matrix and [roadmap](MODEL-QUALITY-001-ROADMAP.md)
remain controlling context. GrowthOS and content production remain outside scope.

## F. Review, reproducibility and next executable gate

Starting checkpoint `12fa98b977b99b75ac8dc37754701ee99dcfea9b` passed all 20 jobs in
[run 42321646466](https://github.com/sebgreenhalgh/dmf-pulse/actions/runs/42321646466).
Engineering checkpoint `466849ac330eba439371e54a5af42b2190909b7e` was independently
verified against all 2,018 Git blobs before its push; its CI is
[run 42334930131](https://github.com/sebgreenhalgh/dmf-pulse/actions/runs/42334930131).
All 20 engineering jobs passed. This does not stand in for the later source checkpoint's FULL gate.

Independent review cleared P0/P1/material P2 for executed branch cleanup, native
cache/recovery outcome, feedback/CI controls and all research slices. Valid
findings were corrected, including ACL order, exact source custody, push-event
binding, manifest preservation and ZIP overwrite/duplicate/opaque payload safety.
The original sealed manifest and all failed attempts remain; current continuation
manifests advance with source while prior committed versions stay immutable in Git.

A final secret-scan attempt correctly stopped on base64-encoded Hypothesis statistics and a compressed metadata sentence. The native XML and failure receipt remain private/preserved. Public JUnit exports losslessly decode those library statistics to readable text, record native/export hashes and preserve every testcase unchanged. The scanner and allowlist were not altered.

Final source hashes, command/JUnit/coverage receipts, before/after summaries,
review and remaining gates are under `evidence/tickets/DMF-MODEL-QUALITY-001/resume`.
Exact reviewed/accepted HEAD and CI observations are bound in the detached review
receipt. Build from clean HEAD with
`uv run --frozen python tickets/DMF-MODEL-QUALITY-001/build_review.py --continuation`;
after FULL, supply its `--full-receipt` capture to reauthenticate/include the actual
result. Pending/FULL packets have separate immutable paths, exactly 20 flat files,
<=32 MiB payload, CRC/digests and source-freeze checks. An existing altered ZIP is
preserved/refused, including duplicate entries, comments and trailing payloads.

Next executable gate is the exact final-SHA FULL check and any smallest valid
correction it identifies. Further storage reduction needs independent wheel/
temporary-output qualification; real research needs source/intent/native custody
acceptance. No unresolved item is silently converted into approval.

### Cold-adapter acceptance follow-up

Checkpoint `a6ae92e6e05951e72a4b817b9fa1e66b66861641` passed all 16 coverage
shards and their combined gate. Its post-coverage cold-adapter benchmark failed
twice at the unchanged 100 ms wall budget (413.5 ms and 491.2 ms); later checks
were skipped. Those failures and the FULL checker's refusal remain preserved.

The follow-up runs the original thirty-call benchmark in a fresh pytest child,
matching its accepted module-only timing context. The parent remains part of
repository-wide performance selection. The full first authentication, all thirty
calls, unique-output assertion and `< 0.1` wall budget are unchanged. It requires
one cache miss and 29 hits, validates exact native JUnit/proof, rejects failed,
skipped, missing or malformed work, and retains/emits bounded native evidence.

Independent guard review and 29 adversarial supervisor controls pass. Native
Windows repository-wide performance selection passes all five cases in 51.45 s,
with a 95.24 ms cold child. An earlier 106 ms Windows child failure remains valid.
Matching CPython 3.13.18 Linux profiles and collection controls did not reproduce
or explain the hosted timing failure; major GC and Python patch drift remain
unsupported causes. This is an isolation candidate pending fresh exact-source
FULL, not a demonstrated numerical speedup. Package, model, dependency, rules,
workflow, coverage and timing limits remain unchanged. Diagnostic Linux runtime
and wheel caches add storage; no new net reduction or deletion approval is claimed.

## G. Owner action

Only the verified contents of
`C:\Users\sebgr\Documents\DMF_PULSE_ARCHIVE_PENDING_OWNER_DELETION`
are prepared for owner deletion. The agent has not deleted this archive. Keep
`C:\Users\sebgr\Documents\DMF_PULSE_CLEANUP_RECOVERY_20261107` and the protected
operating/research assets. The 101 cache sources can be recompiled from retained
source; no evidence, application install, signed wheel, database or worktree is
being delegated for deletion. No action is requested on HOLD material.
