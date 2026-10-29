# ACCEL-002 independent numerical/view integration review

Reviewer: delegated projection audit agent; no tracked source authored or changed.
Scope: Stage-7 assumptions and Stage-9 projection fidelity, one-/three-GW decision parity,
catalogue/missingness, fixture identity, and the view service seam. Source rights and web
security are reviewed separately. Final status: PASS, WITH NO UNRESOLVED P0/P1 OR
MATERIAL P2 FINDING IN THIS REVIEW SCOPE. Eight numerical/provenance runs and the
separate final packaged-demo view run completed successfully.
This is not human acceptance or activation.

## Proposed checks

`review_pack/accel002_parity.py` runs the accepted parent
`02576a563179e0a8d3311fc5e82c770905975f61` and current source in separate
socket/DNS-blocked processes with the same injected synthetic one-command inputs.
It runs native authenticated and explicitly SYNTHETIC TEST ONLY controlled provenance
for one and three Gameweeks (eight complete real-stack executions).

Each artifact preserves full decision JSON, full Gameweek projections, optimizer result,
actual source build identity, effective market identity, exact Python-source hashes and
the current table/detail/two-player comparison proof. Current presentation fields are
checked against captured underlying core results for all projected players.

Controlled identity patches affect `normalisation.code_identity`,
`consensus.code_identity`, and FPL rights-registry identity lookups inside isolated test
workers. The FPL registry has one appended owned synthetic profile; every pre-existing
profile is first compared exactly with the accepted parent, and the real registry loader
and rights gates remain active. Both actual and controlled identities are recorded.
All existing real normalization, source verification, request validation and decision sealing execute unchanged. There
is no production flag, verifier bypass, provider traffic, real credential or production
data. Source-byte changes during any worker or the full run fail the harness.

Native comparison checks every summary numerical field, coherent scenario weights,
points/components/minutes/BPS/bonus/appearance, joint matrix and MC diagnostics. It
also compares complete decision content after declared provenance fields are removed,
retaining exact original JSON and differences for inspection. Controlled comparison
requires exact complete decision/projection/optimizer JSON equality.

## Findings communicated to implementation author

| ID | Severity | Finding | Status |
|---|---|---|---|
| PROJ-01 | P2 | Three-GW PlayerRow fallback flag was always false despite real fallback IDs in rolling decision lineage. | FIXED; all 120 one-/three-GW flags checked against real decision evidence. |
| PROJ-02 | P2 | Fixture kickoff joins by (GW,home,away) can borrow another fixture's metadata instead of using exact canonical/official fixture identity. | FIXED; builder now uses passed exact fixture IDs and checks unique official ID, GW and team orientation. Real fixture-summary copy verified. |
| PROJ-03 | P2 | Upcoming fixtures are carried in player rows but omitted from player table. | FIXED; actual modelled fixture column rendered. |
| PROJ-04 | P2 | Mandatory all-player scoring contribution columns are available only on detail; table currently omits goals/assists/clean-sheet/bonus. | FIXED; direct component means in typed rows and sortable table; all 120 copied values verified in final demo. |
| PROJ-05 | P3 | Frontier FT-next UI reads `at_next_deadline` instead of exact existing `next_decision_deadline`, falling back to report. | FIXED; exact field referenced in inspected JS. |

## Source review observations

- The opt-in typed presentation seam consumes existing completed one-/three-GW run
  results and fixture results; it does not call a second numerical model.
- Sealed decision, lineage and numerical summary schemas remain unchanged in inspected
  edits. The fixture retention addition is on transient dataclass run results.
- Component means are copied unchanged; all 13 names and their sum are validated with
  absolute floating tolerance `1e-10`. No independent component error bars are created.
- Three-GW player means sum already calculated GW means; no horizon PMF/quantiles are
  fabricated. Multiple-fixture probabilities remain null with fixture detail available.
- Full provider catalogue is preserved while removed/unmapped and absent projections
  retain null xPts. Optimizer candidate pruning is not used as projection coverage.
- Stage-7 minutes/start/60+ values are copied from existing fixture projections as exact
  decimal strings; source availability percentages are not substituted.
- Packaged dashboard demo now injects a genuine removed player in its synthetic FPL
  source. Independent final-source execution proves 121 catalogue rows, 120 valid
  projections, one `REMOVED_UNMAPPED` null result, and unavailable detail with no
  fabricated projection. All 120 actual projections remain browsable.

## Final source freeze and native execution

The initial current-source identity was `bd47b7f01bd9fd98961f3cb8f39c4d6d9b6c27ba2b8ac7f3ffaa9dbf91ad5f81`.
The author then changed exactly two Python files: FPL ingestion migration-head revision
0006 to 0007 and the dashboard fake bearer marker to scanner-recognized `placeholder`.
Initial artifacts are retained under `*-before-final-freeze.*`. Current one-GW and the
121-row demo were rerun; all remaining current cases use the final source bytes.

Final Python inventory: 359 files; canonical manifest SHA-256
`a0b10c25ed36b21bb6bdf2eccd088289f80d811d0d9f2f081e0af7030bc563e0`.
Final native market build identity:
`dmf-pulse-0.2.0:source-sha256:ba24b0b4f93af33668575a9fbbd25602661353651c938901aabfc3bb8708759c`.

Native parent/current one- and three-GW numerical projection content is exactly equal,
including all player summary values, coherent scenarios, covariance and MC diagnostics.
Decision content excluding declared provenance is exactly equal. Original complete
decision JSON and unequal native hashes are retained; the added synthetic rights profile
and real package source identity correctly propagate through provenance seals.

Final packaged-demo receipt: `review_pack/accel002-parity/demo-121.json`.
It checks all 120 real model summaries/details/two-player comparison, exact Stage-7
minutes/start/60+ values, 13 components, fixture summaries, four table contribution
fields and all 120 actual historical fallback flags. This is synthetic engineering
evidence, not real current-season coverage, predictive validation or production authority.

## Completed independent acceptance

| Comparison | One GW | Three GW |
|---|---|---|
| Native all projection numerical values and decision content excluding declared provenance | EXACT | EXACT |
| Native complete sealed JSON | Expected provenance difference | Expected provenance difference |
| SYNTHETIC TEST ONLY controlled complete decision JSON | EXACT | EXACT |
| Controlled complete Gameweek projection JSON | EXACT | EXACT |
| Controlled complete optimizer result JSON | EXACT | EXACT |
| All current table/detail/two-player/minutes/component/fallback checks | 120/120 | 120/120 across GW2/3/4 |

The final synthetic packaged demo independently proves 121 catalogue / 120 valid /
one removed-unmapped unavailable row, with exact component and fixture copies.
The private decision models, rolling decision models and Stage-9 numerical models
are byte-for-byte identical to the accepted parent. Browser source was checked for
the corrected FT-next field and rendered fixture/contribution columns.

The initial batch correctly exited 1 at its whole-batch source-freeze guard after
the declared two-file author change. Its before-freeze successful artifacts remain
available. Resuming reverified each worker's exact package source inventory; only
the rerun final current bytes are accepted. `freeze-transition.json` records the
failure and remediation; no numerical failure was recast or discarded.

Commands executed from the ACCEL-002 worktree:

```text
.venv/Scripts/python.exe review_pack/accel002_parity.py --parent ../ACCEL-001-PRIVATE
.venv/Scripts/python.exe review_pack/accel002_parity.py --worker --code-root . --horizon 1 --output review_pack/accel002-parity/native-1gw-current.json
.venv/Scripts/python.exe review_pack/accel002_demo_review.py
.venv/Scripts/python.exe review_pack/accel002_parity.py --worker --code-root . --horizon 3 --controlled --output review_pack/accel002-parity/controlled-3gw-current.json
.venv/Scripts/python.exe review_pack/accel002_parity.py --parent ../ACCEL-001-PRIVATE --resume
.venv/Scripts/python.exe review_pack/accel002_review_finalize.py
```

Only ignored review files were authored by this reviewer. Native IDs and unequal
full hashes are preserved; the explicitly synthetic controlled workers do not change
production code authentication, source-rights permissions, numerical policies,
sealed schemas, P01, A04, metadata policy or activation state.

## Bounded evidence bindings

| Artifact | SHA-256 |
|---|---|
| `accel002-parity/independent-review-receipts.json` (16,288 bytes; all eight full-artifact hashes) | `5d62bd1bb72278d9080b566c62edb8c3c6d611fbaf621c3910522cf9a86da094` |
| `accel002-parity/summary.json` (48,951 bytes; final source inventory and comparisons) | `d0bc8766692462434d8c9c27572ac8b3dacea79b3e564085ed1a578bab71a553` |
| `accel002-parity/demo-121.json` | `937f21340f062a7e29c6fb93ae066443bcb4e9a47a7782c1177de56c3417d168` |
| `accel002_parity.py` | `5625e2f17936eedaef6e8f91298e5db4191031536cf7e11c7714e14ce463d305` |
| `accel002_demo_review.py` | `64ff55fd2ddb56ab9a0f78c3a45c1d9222df3c90bbf8c28814a9e4a195fd07ce` |
| `accel002_review_finalize.py` | `ffde7475049e479781a49d01abda9847eb230d29ee18212ce2ac1908f4b42e5d` |

Full synthetic projection/decision payloads remain in ignored `accel002-parity/`;
use the bounded receipts for the capped review pack. No real source body or private
provider artifact is included. This review establishes engineering parity on the
tested synthetic one-/three-GW family; it does not establish football predictive
accuracy, full CI completion, installed-wheel acceptance, or human acceptance.
