# R9B local acceptance results

These are local candidate results, not an exact-SHA CI certificate. Publication
requires independent clearance and a subsequent all-green exact-SHA run.

| Gate | Observed result |
| --- | --- |
| Final focused R9B tests | 85 passed, 31.00 seconds |
| Broad ingestion / availability / points / private / R7 / rolling regressions | 1792 passed, one warning, 4783.82 seconds |
| Three added production modules | 458/464 statements, 127/134 branches; combined 97.8261%; zero coverage exclusions |
| Ruff format / check | 810 files formatted; all checks passed |
| Strict mypy via Python module | No issues in 291 source files |
| Frozen sync | 40 locked packages checked |
| Build | Both 0.2.0 sdist and wheel built |
| R9B clean external wheel | PASS; network blocked; source/installed synthetic shadow hashes equal |
| Active frozen parent differential | Every field except disclosed native build identity and timing exactly equal |
| Live FPL / Odds / recommendations / credential inspections | Zero |
| Optimisation/points performance smoke | 2 passed, 6.93 seconds |

The larger canonical database-aware wheel verifier stopped because no local
DMF_TEST_DATABASE_URL was supplied. It did not pass locally. The dedicated R9B
external installed-wheel test above passed; complete database CI is still required.

The broad suite started before the final extra contract tests and the outfield-save
guard refinement; the 85-test final focused run includes those final changes.
No existing production module is edited. Broad tests exclude postgres, migration
and performance markers; complete CI remains mandatory, including database jobs.
The broad run suppressed warning detail; its one warning is not a failure. Earlier
focused Pydantic warning construction was corrected and the final focused run has
no warning summary. No warning filter or coverage threshold was weakened.

Uncovered production lines are defensive checks for cross-world catalogue mismatch,
an independently invalid structural-zero rate, unrepresentable assist weight,
duplicate current event identity, stale/resource lineage mismatch and absent donor.
One team-TV branch with an entirely zero-weight team is unvisited. These checks
remain in place; coverage is not represented as complete.

The installed wheel contains the historical compact resource and implementation.
Its synthetic shadow hash is
`920040e9f0415be5c715478840a89728daf6a6b5d002aca048f60c07fc4412d5`.
It imports from a disposable environment outside the repository, with no source/test
imports there, and makes zero provider requests. This is not a live probe.

## Synthetic diagnostic interpretation

The generated 659-player catalogue resolves all players: 1 individual same-team and
658 position-fallback assignments. All 1797 historical donor/world rows are present
and unique. The synthetic window has 2636 rows and 659 minutes/starts matches, not
the user-supplied live 2549 rows / 610 complete / 49 partial metadata. No live
assignment breakdown or current player values were inspected.

Three-world compile warm-up is excluded. Final three-sample median is 2.1722s;
resource loading is outside timing. An earlier run under concurrent regression
load measured 5.35s. These are local compiler timings, not total live acquisition,
summary, projection or recommendation latency, and not a cross-machine guarantee.

Stage-9 ablation uses 256 paired scenarios, 22 synthetic players and reference-only
rules. The reported 15-player points sum is a declared raw scoring subset, not a
legal manager XI, captain/autosub score or transfer decision. ALL_SUPPORTED mean
absolute player xP movement is 0.318537, p90 0.577344, subset mean delta -1.546875,
paired median -1, p10 -7, p90 +3 and probability of positive delta 0.273438.
Fixed named streams/indexes preserve coupling, but conditional draw consumption and
finite Monte Carlo error mean these are not exact analytic component effects.

The separate target-rules Stage-10 experiment uses 16 scenarios, three fixtures and
two legal provided squads. It preserves the sealed cumulative work limits and
canonical final tactical verification. Squad choice, captain and XI do not change;
expected manager utility delta is -0.9375. Price/hit/FT scope is not modeled. A
rolling Stage-11 shadow decision is **not executed**, represented as null rather
than false. This demonstrates measured movement, not improved predictive accuracy.
