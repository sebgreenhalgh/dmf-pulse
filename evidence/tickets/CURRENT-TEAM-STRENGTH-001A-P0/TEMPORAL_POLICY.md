# Source finality and freshness policy

For a `LIVE_OBSERVED` cutoff `T`, a result is eligible only when it is from an immutable commit
and validated file hash, was received and validated before `T`, has `received_at <= T` and
`usable_at <= T`, maps exactly to one canonical fixture and two canonical clubs, contains a
recognized full-time score, and has no postponed, abandoned, cancelled, suspended, unknown
nonempty, or otherwise non-final status.

`eligibility_not_before(row)` is `00:00:00Z` on the source played match date plus two calendar
days. Same-day and immediate-next-midnight use are forbidden. A revised played date must pass the
same rule. Corrections are immutable descendants and never mutate a frozen historical forecast.
Ambiguous or abandoned results remain quarantined pending governed resolution.

For `RECONSTRUCTED` evaluation, final-current-vintage scores may be explicit reconstructed
labels/inputs. They are not evidence that a result was operationally available at a historical
deadline.

Freshness is based on due-result completeness, exact validation, and age since the latest
successful usable snapshot retrieval—not repository/commit age:

- `FRESH`: `missing_due == 0`, validation passes, retrieval age `<= 24h`; refit allowed.
- `DEGRADED`: `missing_due == 0`, validation passes, `24h < age <= 72h`; retain the latest sealed
  artifact with a visible warning and make no newly fitted/current claim.
- `STALE_BLOCKED`: any missing due row, age `> 72h`, unresolved mapping, ambiguous status,
  invalid schema, or invalid lineage; do not create a new/current artifact and use the governed
  league-level support prior fallback only where otherwise legal.

The enclosing governance artifact semantic SHA-256 is
`ff04de46f08711d85fb0de24f5a9257618b82d7422ae349bff2e033d082f4d21`.
