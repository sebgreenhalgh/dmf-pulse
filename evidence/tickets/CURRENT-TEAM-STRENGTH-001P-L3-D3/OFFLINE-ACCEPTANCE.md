# D3 offline acceptance

Immutable parent: `b774056f20e855d7a755186fe62489e3d393ecfe`.

The implementation introduces `PreparedRollingControlFlow(Exception)`. D1
`TeamStrengthComparisonFailure`, D2 `_LiveWrapperFailure`, and successful
`_ObservationComplete` inherit from that explicit family. The real one-command
service reraises only this family before its unchanged ordinary
`ValidationError`/`ValueError`/`ArithmeticError`/`KeyError`/`TypeError` sanitizer.

The prepared callback advances its outer fallback to
`INVOKE_TWO_WORLD_COMPARISON / COMPARISON_INVOCATION_FAILED` after obtaining a
non-null shadow and before invocation. A genuinely unavailable shadow retains one
of `SOURCE_STALE`, `CURRENT_ARTIFACT_UNAVAILABLE`,
`CURRENT_SOURCE_ASSESSMENT_UNAVAILABLE`, or `INCOMPLETE_FIXTURE_COVERAGE`.

All acceptance uses generated/provider-shaped offline inputs. FPL, Odds and live
OpenFootball requests are zero; credentials were not inspected. L1, L2 and L3 are
consumed, and no L4 authority exists.

## Verification

- Real full-seam D1/D2/ordinary-ValueError/historical-interception family: 5 passed.
- Four finite shadow-preparation reasons: 4 passed.
- D1/D2, authority, wrapper and ordinary one-command population: 204 passed.
- Real completion seam plus five locked 001P numerical/decision cases: 6 passed.
- Public readiness, Stage 8/9/10/11, rolling and one-command population: 114 passed.
- Public CLI surface: 3 passed.
- Frozen offline dependency sync: 40 packages.
- Repository-wide Ruff format/check and strict mypy across 313 source files: passed.
- Git whitespace validation: passed.
- Wheel and sdist build: passed.
- Clean installed-wheel authority/diagnostic/operator-help smoke: passed; provider
  calls remained zero.
- First-party secret scan: passed with zero findings.
- Instrumented D3/D1/D2/authority population: 154 passed.
- Combined branch coverage for the D3-owned control-flow, diagnostic, live-wrapper,
  and live-authority surface: 96% (487 statements, 76 branches). The explicit
  one-command typed rethrow and ordinary sanitizer behavior are both exercised.
- Repository validator: passed with zero errors.
- Capped deterministic review pack: 20 entries.

Exact-SHA run `35889911797` proved the corrected clean manifest and passed seven
of eight coverage shards. The remaining shard reached its 35-minute job limit
at 93%, immediately after inherited tests and while entering the four real D3
seam cases; it reported no assertion failure. The deterministic planner now
assigns the measured D3 module a static balancing weight. This changes no test
selection, timeout, coverage gate, production code, or model/decision behavior.
Run `35896662500` confirmed that a measured-runtime weight alone still left
approximately 24 minutes of inherited default-weight work beside D3. The D3
module initially used the planner's existing `1800` heavy-module tier rather
than weaken tests or widen the job timeout.
Run `35902055457` then proved that D3 itself completed on its isolated shard, but
two other shards exposed inherited modules whose node-count estimates materially
understated their measured branch-coverage runtime. Their exact-SHA measured
costs are now represented by deterministic static total-file hints. This remains
scheduling-only: all 5,297 eligible nodeids stay complete and disjoint under the
unchanged `not performance` selector and 35-minute job limit.
Replacement run `35909009743` passed pre-flight and seven of eight shards. Its
sole remaining timeout contained the legacy R2C assurance module (946 seconds),
an inherited repository-persistence module (270 seconds), and other measured
costs; it reached 91% with no assertion failure. R2C was moved into the heavy
tier, and the newly measured inherited costs received explicit static hints.
Run `35914280411` then passed pre-flight and five shards. Parallel-runner timing
showed D3 at 1,482 seconds, the five-case module still executing after 1,697
seconds, and an inherited optimiser service at 734 seconds. D3's shard completed
all 592 tests in 34m38s before cleanup was cancelled; no assertion failure was
reported in any cancelled shard. D3 and the five-case suite then used standalone
`6000` weights, R2C received a conservative heavy hint, and the remaining
measured heavy modules received conservative approximately two-times-wall-time
hints. Selection and gates remained unchanged.
Run `35924448502` passed pre-flight and seven shards. Its sole timeout had spent
about 22 minutes on inherited work before entering the approximately 12-minute
A2 preparation module; it reported no assertion failure. A2 now has a `2800`
hint that prevents another 22-minute coassignment without wasting a shard, and
the last observed inherited 1--4 minute modules have explicit wall-time hints.
The unchanged complete population remains mandatory.
Run `35929503354` then passed pre-flight and six shards, including the isolated
D3 and five-case suites and the rebalanced A2 shard. Its two cancellations
reported no assertion failure. One reached the L1 end-to-end module after about
22 minutes and remained there until the job limit; the other reached the shadow
comparison module after about 27 minutes. The exact logs also exposed a
previously default-weighted 215-second Odds model-configuration module. L1
end-to-end and these newly measured inherited modules now have conservative
static hints so those final slow paths receive materially less coassigned work.
The same run measured isolated D3 at 25m14s and the five-case suite at 27m10s;
the final deterministic partition uses only their proven bounded headroom for
fast coassignment, while the measured L1 end-to-end path receives its own heavy
tier. No selector, test, timeout or quality gate changes.

The six inherited comparison tests that had asserted the old broad `ValueError`
ancestry now assert `TeamStrengthComparisonFailure` plus exact safe stage/reason.
No production mathematics changed to satisfy those tests.

## Final closure

The canonical integrated implementation was published at
`9239630f355007ba3def2b3cab88a2995d749a22` on
`readiness/CURRENT-TEAM-STRENGTH-001P-L3-D3-prepared-runner-diagnostic-propagation`.
Local and remote refs were equal and the tracked worktree was clean. Exact-SHA
GitHub Actions run `36028866023` completed successfully, including all 16
coverage shards, the combined branch-data gate, post-coverage acceptance,
installed-wheel verification, repository validation, and the first-party secret
scan.

The Phase 1--3 CI remediation commits are infrastructure/test changes. The five
D3 production paths remain byte-identical to implementation commit
`62d3da6567dddd94b5e9e6c1dc5beda0ba67d70d`; the integrated tree therefore
preserves the independently reviewed D3 semantics. The earlier independent
technical review was conditional only on clean publication, remote equality,
and green mandatory exact-SHA CI. Those objective conditions are now satisfied;
no new independent human review is claimed.

The bounded historical L3 conclusion remains exactly:

- shadow preparation succeeded sufficiently to start comparison invocation;
- comparison invocation did not return normally;
- the historical detailed failure was erased by the proven `ValueError`
  interception mechanism;
- the exact underlying historical comparison failure remains unknown.

L1, L2, and L3 remain consumed. No L4 authority, approval, attestation, provider
access, retry, or production activation was created or performed during closure.

Final verdict: `CLEAR_FOR_TEAM_STRENGTH_L4_REAUTHORIZATION_DECISION`.
