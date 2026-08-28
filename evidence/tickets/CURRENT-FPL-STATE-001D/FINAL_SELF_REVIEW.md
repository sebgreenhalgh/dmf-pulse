# CURRENT-FPL-STATE-001D same-agent remediation self-review

This review follows independent findings against deficient commit `049753...`. It does not claim
the implementation agent originally found those defects, that independent re-review has passed,
or that human acceptance has occurred.

| Severity | Found historically | Closed by remediation | Unresolved |
|---|---:|---:|---:|
| P0 | 0 | 0 | 0 |
| P1 | 1 | 1 | 0 |
| Material P2 | 1 | 1 | 0 |
| P3 | 0 | 0 | 0 |

## CFSC-001D-IR-001 — P1 — closed

Root cause: 001D bound 001A's acquisition semantic SHA and the reduced 001B/001C views, but did
not bind the complete materialized `CurrentFplInputBundle`. Material non-view fields could
therefore change without changing unified identity.

Remediation: a complete canonical materialized-object representation digest is recomputed from
the supplied 001A object and retained separately in request and lineage. Unified identity already
binds lineage. Accepted 001A code and its acquisition digest remain unchanged.

Adversarial answer: two materially different `CurrentFplInputBundle` objects cannot retain the
same unified identity merely because a change lies outside identity/catalogue views. All 12
reported mutation classes change the full digest; stale requests block; fresh valid requests
produce a different unified SHA; attacker-rehashed nested/top-level bundles fail against the
stale external family. Reordering only accepted identity-keyed catalogues does not change the
digest.

## CFSC-001D-IR-002 — material P2 — closed

Root cause: upstream identity and manager verification `IngestionError` objects could cross the
001D boundary with provider/private values in `details` or messages.

Remediation: all upstream identity binding/resolution failures and manager service verification
failures are translated locally to generic `MAPPING_CONFLICT` errors with no details. Safe
001D-native error classifications remain intact.

Adversarial answer: upstream identity/manager reconstruction errors expose no material
private/provider-specific content through `details`, `as_error_object()`, `str`, or `repr`. Tests
exercise all four identity calls, actual incomplete coverage with internal synthetic fixture ID
`900103`, and manager catalogue/source and rules failures.

## Preserved P0 boundaries

- 001B identity and 001C manager families are reconstructed against exact supplied sources.
- Cutoffs remain identical and strictly no later than the FPL-authoritative deadline; readiness is
  the latest required source usability/mapping time.
- FPL-derived persistence, raw/derived storage, cache, backup, public display, redistribution,
  automated official-FPL access, network, and database use remain denied.
- All committed current-state facts are synthetic.

## Preserved P1/P2 behavior

- Odds price semantics and acquisition provenance remain independently bound.
- Reduced FPL identity and manager catalogue views remain separate accepted contracts.
- Manager state remains `OPERATOR_DECLARED`, `HUMAN_ATTESTED`, and
  `NOT_PROVIDER_VERIFIED` under ACTIVE FULL_SEASON rules.
- GW2+, multiple target fixtures, unrelated future Odds events, common cutoff, decision time,
  source substitution, and the original rehashed tamper population remain green.
- Safe summary content remains allowlisted and excludes provider/private facts.

## Acceptance summary

- Focused: 114 passed; branch-aware coverage 94.46640316205534%.
- Accepted 001A/001B/001C: 218 passed; LIVE-ODDS: 223 passed.
- Rules: 151 passed; broad Stage-11: 322 passed; broad Stage-14: 405 passed.
- PostgreSQL 18.4: 126 passed, 140 deselected; migration matrix PASS.
- Frozen sync, diff, Ruff, mypy, build, generic/ODD/GCS wheels, and direct installed-wheel 001D
  exercise: PASS.

Independent re-review is still required. No PR, merge, production activation, or human acceptance
is claimed.
