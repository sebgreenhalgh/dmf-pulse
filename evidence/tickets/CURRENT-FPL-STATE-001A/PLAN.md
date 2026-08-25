# CURRENT-FPL-STATE-001A plan

1. Reconcile only the donor current-FPL compiler against current main and record exact lineage.
2. Generalize target-Gameweek handling without claiming unsupported multi-season behavior.
3. Preserve the existing parser and current rights authority; add no transport or persistence.
4. Expose immutable private bundle contracts and a disclosure-minimized CLI summary.
5. Add fail-closed unit, CLI, path, temporal, rights, cross-resource, and disclosure tests.
6. Run branch-aware focused coverage, inherited FPL regressions, static/build/wheel/security gates,
   seal review evidence, push the final SHA, and inspect its automatic CI once.

Independent review subsequently identified CFSA-REV-001/002 at
`140100fa49bea1d3d0493cb68f186af564fa1380`. Resume rather than restart the ticket: add RED/GREEN
regressions, make target-event state explicit and descriptor-bound file identity authoritative,
correct overstated evidence, reseal only authorized manifests, repeat every gate, and hand the new
immutable SHA to independent re-review without a post-CI status commit.

No real official FPL payload, endpoint call, credential, database, or repository persistence is
permitted during implementation or acceptance.
