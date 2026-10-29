# ACCEL-002 independent cross-workstream integration review

Review scope: ACCEL-002 worktree based on
`02576a563179e0a8d3311fc5e82c770905975f61`. Source integration is clear after the
corrections below; final release gates remain pending. This is not human acceptance.
No tracked files were edited,
credentials read, provider traffic issued, or Git state changed by this reviewer.

## Confirmed finding INT-001 — P1 — resolved and independently retested

PostgreSQL migration `20261029_0007_player_research.py` uses SQL predicates that
evaluate to NULL when required JSON fields are absent/null. In PL/pgSQL an IF
condition of NULL is not taken, allowing malformed artifacts through the claimed
custody and cohort boundary.

Rollback-only independent reproductions against the disposable local PostgreSQL
instance established:

- An otherwise qualified FORECAST with `recorded_at` missing or null is admitted.
- An EXPERIMENT with `registered_at`, `promotion`, or `dataset_mode` missing or null
  is admitted.
- A SCORECARD with `count`, `forecast_hashes`, `label_hashes`, and `promotion`
  removed, and no score pairs, survives the actual deferred constraint triggers
  after `SET CONSTRAINTS ALL IMMEDIATE`.

Every mutated payload had a valid recomputed canonical hash. The nested forecast
was confirmed present in the database's qualified forecast allowlist, so this was
not a qualification-failure false positive. All database mutations were rolled back.
Original reproduction receipt: `accel002-sql-null-review-before.json`.

The implemented correction authenticates exact qualified synthetic experiment and
scorecard identities, enforces an exact three-key FrozenForecast wrapper with an
aware timestamp, and fails closed on NULL in custody/count/pair validation. The
independent rerun rejects all 13 malformed missing/null/naive/extra-field cases;
the positive qualified forecast is admitted. Temporary tables omit unique indexes
but invoke the real artifact trigger, proving rejection is by the intended guard
rather than an existing target/model conflict. The empty scorecard/no-pairs attack
also fails on the real artifact table. All mutations were rolled back.
Correction receipt: `accel002-sql-null-review.json` (PASS).

## INT-002 — P2 provenance hardening — resolved and independently retested

At initial review `player_lab.require_sources` checked a SourceRef against
registry metadata, but does not hash the referenced packaged resource. The
analytic forecast loader reads `forecast-inputs.json` without checking the
registered payload SHA. The exact forecast allowlist blocks changed forecast
values; an unused additional field can nevertheless leave recorded source
identity inaccurate. Hash registered owned resources at admission/loading and
exercise a tamper case. Actual-label ingestion and dashboard demo inputs already
authenticate their body bytes. The corrected source gate now hashes each
registered owned resource before admission. Its dedicated tamper test passes.

## Integration observations

Accepted DMFP-20 ADR-OPS-006 supplies the FastAPI/shared-service authority; the
proposed DMFP-16/18 documents are not treated as wholesale accepted authority.
The observed diff does not modify production Stage-9 model contracts, numerical
kernels, current Availability projections, protected P01 configuration, or the
mandatory CI workflow. The presentation seam copies actual completed summaries
and keeps the sealed decision contracts unchanged.

`dmf dashboard --help` works. Ordinary Refresh explicitly blocks at the market
rights boundary before worker/provider/credential use. The synthetic refresh
uses the genuine private service and real downstream stages with injected
owned sources. Session/origin guards, finite memory views, disposable workers,
no-store/CSP controls and browser epoch cancellation are present; the separate
security reviewer should bind their adversarial browser proof to the final JS.

Independent command:

```
.venv/Scripts/python -m pytest tests/unit/player_lab tests/unit/database/test_dat003_branch_contracts.py --basetemp=review_pack/pytest-integration-review -o cache_dir=review_pack/cache-integration-review -q
```

Result: 65 passed in 6.14 seconds, zero skips. This does not cover the confirmed
SQL missing-field cases, which were run independently above.

After the corrections, a fresh independent run of all `tests/unit/player_lab`
passes 59 tests in 3.08 seconds, including the resource tamper test and seven
actual Stage-9 snapshot tests. The retained owned Stage-9 output is authenticated
by bytes and semantic hash, copied without mean/component recomputation, admitted
to the ledger before opening the later finalized exact-fixture synthetic label,
then scored by the existing Stage-12 kernels. Forecast metadata and coherent
outcome-informed substitutions fail qualification. This is synthetic acceptance,
not real historical evidence or model promotion.

## Final clearance prerequisites

- Bind one/three-GW numerical parity, real browser and clean installed-wheel
  demonstrations to the final code and packaged resources.
- Complete migration matrix, PostgreSQL guards, actual schema SHA, repository and
  runtime lock manifests, security/build/frozen sync/coverage and literal gates.
- Retain five-scope independent review and final exact-SHA 20/20 CI, local/remote
  equality, protected artifact checks and original dirty-worktree preservation.

No unresolved P0, P1 or material P2 integration finding remains in the reviewed
source. A minor display limitation remains: missing-player null start/60+
probabilities read "Per fixture" beside the explicit REMOVED_UNMAPPED reason.
This is a P3 clarity issue and does not fabricate a numeric projection.

Final release clearance still depends on the outstanding acceptance receipts and
the exact pushed SHA. The companion JSON records the source-byte binding.

## Packaging remediation supplement

The clean-wheel exercise found the inherited FPL ingestion service still expected
schema revision `20260807_0006`. Its constant now requires the new exact current
revision `20261029_0007`; the revision mismatch denial and all rights/transport
checks are unchanged. The synthetic demo credential string changed to the
repository's recognized `placeholder` marker. It remains an injected owned fake
value and does not affect model inputs or numerical calculations. The dashboard
test's cookie argument was renamed to avoid a scanner false positive; it still
passes the same HTTP Cookie header and preserves the disclosure assertion.

Independent focused rerun:

```
.venv/Scripts/python -m pytest tests/unit/ingestion/test_fpl_service_boundaries.py tests/unit/database/test_database_contracts.py --basetemp=review_pack/pytest-integration-review-rebind -o cache_dir=review_pack/cache-integration-review-rebind -q
```

Result: 66 passed in 3.46 seconds, zero skips. Inspection found no numerical,
provider-rights or live-acquisition behavior change. A fresh installed-wheel
receipt remains required for this packaging correction.

Rebound to checkpoint `de50b54692f481206ad8f59a1f477089b1fcf01f`: the companion
JSON records 70 working-tree byte hashes and 70 immutable Git blob byte hashes,
including the newly reviewed FPL schema constant, synthetic marker and installed
wheel probe. Source integration remains clear. Later evidence-only commits may
bind these unchanged file identities without altering this code review.
