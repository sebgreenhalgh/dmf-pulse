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
module therefore uses the planner's existing `1800` heavy-module tier to isolate
the unchanged seam cases rather than weaken tests or widen the job timeout.
Run `35902055457` then proved that D3 itself completed on its isolated shard, but
two other shards exposed inherited modules whose node-count estimates materially
understated their measured branch-coverage runtime. Their exact-SHA measured
costs are now represented by deterministic static total-file hints. This remains
scheduling-only: all 5,297 eligible nodeids stay complete and disjoint under the
unchanged `not performance` selector and 35-minute job limit.
Replacement run `35909009743` passed pre-flight and seven of eight shards. Its
sole remaining timeout contained the legacy R2C assurance module (946 seconds),
an inherited repository-persistence module (270 seconds), and other measured
costs; it reached 91% with no assertion failure. R2C now uses the proven `1800`
heavy tier, and the newly measured inherited costs have explicit static hints.

The six inherited comparison tests that had asserted the old broad `ValueError`
ancestry now assert `TeamStrengthComparisonFailure` plus exact safe stage/reason.
No production mathematics changed to satisfy those tests.
