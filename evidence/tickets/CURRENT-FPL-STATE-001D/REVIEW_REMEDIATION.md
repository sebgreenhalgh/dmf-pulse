# CURRENT-FPL-STATE-001D independent-review remediation

## Reviewed defect identity

- Architectural parent: `716ea3a90c8893081bfebce400020b07ce95a463`.
- Deficient reviewed SHA: `049753583053245d6ffce4c1f37da09724b59103`.
- Deficient tree: `d84f153cbc996d09382a7fc4a5c80edf935fb172`.
- Deficient exact-SHA CI: run `33123304133`.
- Independent verdict: `CURRENT_FPL_STATE_001D_REMEDIATION_REQUIRED`.
- Remediation identity: `FINAL_REMEDIATION_COMMIT_CONTAINING_THIS_EVIDENCE`, with exact SHA in
  Git history and the final handoff. Embedding that SHA in its own commit is cryptographically
  self-referential, and a post-CI evidence commit is forbidden.

## CFSC-001D-IR-001

- Severity: P1.
- Found by: independent review.
- Root cause: legacy 001A acquisition semantics plus reduced 001B identity and 001C catalogue
  views did not uniquely bind every material field of the materialized FPL object carried by 001D.
- Remediation: `current_fpl_full_representation_sha256` hashes the complete materialized bundle in
  JSON mode through canonical repository SHA machinery. Events, teams, positions, players, and
  fixtures are normalized by accepted identity keys; all remaining representation order is
  preserved.
- Binding: request and lineage recompute the new digest from the actual object; unified semantics
  bind lineage; service verification reconstructs the expected bundle from the external family.
- Accepted 001A modified: no.
- Closure: closed by the remediation commit containing this evidence, pending independent
  re-review.

## CFSC-001D-IR-002

- Severity: material P2.
- Found by: independent review.
- Root cause: upstream identity/manager `IngestionError` messages and details crossed 001D's
  disclosure boundary unchanged.
- Remediation: all four identity binding/resolution calls and manager service verification are
  wrapped locally. Upstream failures become generic detail-free `MAPPING_CONFLICT` errors.
- Safe native behavior: 001D-created `POST_CUTOFF`, `RIGHTS_BLOCKED`, and generic mapping errors
  remain classified at their native boundary.
- Closure: closed by the remediation commit containing this evidence, pending independent
  re-review.

## Regression coverage added

- Twelve independent non-view FPL mutations: status, both chance fields, news, news time, game
  settings, three non-target event state classes, and three fixture state fields.
- Stale request compose and baseline bundle verification rejection for every class.
- Fresh-request composition with a different unified SHA for representative player, game setting,
  non-target event, and fixture mutations.
- Attacker-updated full-FPL lineage plus rehashed outer bundle rejection for every class.
- Catalogue reorder invariance for accepted identity-keyed collections.
- Serialized identity failures for every binding/resolution call.
- Actual incomplete coverage whose upstream error contains synthetic fixture ID `900103` while
  the 001D public error contains no ID or details.
- Serialized manager catalogue/source and rule reconstruction failures containing synthetic
  player, price, bank, FT, captaincy, bench, chip-token, and operator markers.

## Acceptance

- Focused tests: 114 passed.
- Branch-aware coverage: 94.46640316205534%, 220/227 statements and 19/26 branches.
- Accepted 001A/001B/001C: 218 passed.
- LIVE-ODDS: 223 passed.
- Rules / broad Stage-11 / broad Stage-14: 151 / 322 / 405 passed.
- PostgreSQL: 126 passed, 140 deselected; migration/data-preservation matrix PASS on 18.4.
- Frozen sync, Ruff, mypy, build, three wheel gates, and direct installed-wheel 001D probe: PASS.

## Remaining limitations

- The new digest proves exact materialized-object representation at the 001D boundary only. It is
  not provider authentication, acquisition authority, or a truth guarantee for manual capture.
- Official-FPL access remains manual/transient; all storage and automated access remain denied.
- Manager facts remain human-attested and not provider-verified.
- 001D remains a private transient source bundle, not a Decision Bundle, model, optimiser, or
  production activation.
- Independent re-review, PR, merge, and human acceptance remain separate.

## Findings disposition

| Finding | Severity | Historical | Closed | Unresolved |
|---|---|---:|---:|---:|
| CFSC-001D-IR-001 | P1 | 1 | 1 | 0 |
| CFSC-001D-IR-002 | Material P2 | 1 | 1 | 0 |

P0 unresolved: 0. P3 unresolved: 0.
