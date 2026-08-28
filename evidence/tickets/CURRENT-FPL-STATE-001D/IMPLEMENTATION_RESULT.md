# CURRENT-FPL-STATE-001D engineering and remediation result

## 1. Git chronology

- Architectural parent: `716ea3a90c8893081bfebce400020b07ce95a463`.
- Deficient independently reviewed commit: `049753583053245d6ffce4c1f37da09724b59103`.
- Deficient tree: `d84f153cbc996d09382a7fc4a5c80edf935fb172`.
- Deficient exact-SHA CI: run `33123304133`.
- Independent verdict: `CURRENT_FPL_STATE_001D_REMEDIATION_REQUIRED`.
- Branch: `integration/current-fpl/CURRENT-FPL-STATE-001D-unified-current-state`.
- Remediation commit: `FINAL_REMEDIATION_COMMIT_CONTAINING_THIS_EVIDENCE`; its exact Git SHA is
  reported by the final handoff because a commit cannot contain its own content-addressed SHA.
- Exact-SHA remediation CI remains externally observable after push; no post-CI evidence commit is
  permitted.

## 2. Independent findings

`CFSC-001D-IR-001` (P1) and `CFSC-001D-IR-002` (material P2) were found by independent review of
`049753...`, not by the original same-agent self-review. Both are closed by the remediation commit
containing this evidence, subject to independent re-review.

## 3. CFSC-001D-IR-001 remediation

`current_fpl_full_representation_sha256` now canonically hashes the complete materialized accepted
`CurrentFplInputBundle`, including all events, teams, positions, players, fixtures, game settings,
provenance, rights, quality, and existing semantic/provenance hashes. Only accepted 001A
identity-keyed catalogue order is normalized. The digest is bound independently into the 001D
request and lineage, so it also changes the unified semantic SHA.

This is a local 001D representation-integrity binding. It does not authenticate official FPL,
replace 001A acquisition semantics, prove manually captured facts true, or authorize automated
official-FPL access. Accepted 001A source code is unchanged.

The hostile matrix proves every independently reported non-view class changes the new digest:
player status, both chance fields, news, news time, canonical game settings, non-target event
finished/data-checked/state flags, and fixture finished/started/provisional state. A stale request
and substituted external family block. Freshly rebound valid objects compose with a different
unified SHA. The same mutations remain blocked after an attacker updates both nested lineage and
the top-level semantic SHA.

## 4. CFSC-001D-IR-002 remediation

Every upstream team/fixture binding and identity-resolution `IngestionError` is translated at the
001D boundary to detail-free `MAPPING_CONFLICT` / `FPL/Odds identity reconstruction failed`.
`CurrentManagerStateService.verify` failures are translated to detail-free `MAPPING_CONFLICT` /
`current manager reconstruction failed`. Safe 001D-native classifications remain unchanged.

Tests serialize `as_error_object()` and inspect `str` and `repr`. They cover all four identity
calls, real incomplete target-fixture coverage whose internal details contain synthetic fixture
ID `900103`, and manager catalogue/source and rule reconstruction failures. No upstream details,
IDs, provider strings, market or manager-private values survive the public boundary.

## 5. Preserved source behavior

GW2+, strict pre-deadline cutoff, unrelated Odds events, complete target coverage, exact
home/away/kickoff authority, Odds market and acquisition-provenance bindings, accepted identity
and manager reconstruction, ACTIVE FULL_SEASON rules, `OPERATOR_DECLARED`, `HUMAN_ATTESTED`,
`NOT_PROVIDER_VERIFIED`, and transient/private/non-persistent runtime behavior remain unchanged.
The accepted reduced 001B identity and 001C catalogue view contracts remain separate and tested.

## 6. Rights and scope

FPL automated access remains denied. No source acquisition, provider call, database or persistence
by 001D, market normalisation, availability/minutes model, football-event or points model,
optimisation, orchestration, Decision Bundle, production activation, PR, merge, independent
re-review, or human acceptance is implemented or claimed.

## 7. Focused acceptance

- Focused suite: **114 passed**.
- Branch-aware focused coverage: **94.46640316205534%** overall (**94% displayed**), 220/227
  statements and 19/26 branches; `>=90%`: **PASS**.
- Newly required digest canonicalization, request mismatch, external verify mismatch, identity
  upstream translation, and manager upstream translation paths are exercised.

## 8. Inherited acceptance

- Accepted 001A/001B/001C population: 218 passed.
- Accepted LIVE-ODDS population: 223 passed.
- Current rules: 151 passed.
- Broad Stage-11 population: 322 passed.
- Broad Stage-14 chips population: 405 passed.
- PostgreSQL 18.4 integration population: 126 passed, 140 deselected.
- Migration/data-preservation matrix: PASS through revision `20260807_0006`.
- 001D product code remained network-free, database-free, and non-persistent.

## 9. Static, build, and installed wheel

Frozen sync checked 40 packages. Diff hygiene, Ruff format/lint, and mypy over 251 source files
pass. The approved host build produced the sdist and 292-member wheel after Windows sandbox
application control denied the launcher before execution. Generic, ODD-005, and GCS-008 clean
wheel verification pass; ODD-005 made zero network requests.

A separate offline environment outside the source tree imported
`dmf_pulse.ingestion.current_state` from installed `site-packages` and passed full FPL
representation binding, stale-request rejection, fresh-rebind changed identity, compose, verify,
and safe identity-error translation.

## 10. Evidence and status

Canonical CURRENT-FPL-STATE-001D and authorized mutable PRC-013 manifests, repository validation,
and secret scanning are sealed after final evidence content. Independent findings remain explicit;
the original deficient commit is not amended or rewritten.

Same-agent remediation review records unresolved P0 = 0, P1 historical/closed/unresolved =
1/1/0, material P2 historical/closed/unresolved = 1/1/0, and unresolved P3 = 0. Independent
re-review remains required.

Status after exact-SHA CI is green:

`CURRENT_FPL_STATE_001D_REMEDIATED_PENDING_INDEPENDENT_REREVIEW`

Next action:

`INDEPENDENT_REREVIEW_CURRENT_FPL_STATE_001D`
