# PRIVATE-V1-ONE-COMMAND-001D engineering acceptance

The current-FPL game-settings adapter must recursively accept every JSON value admitted by the
strict parser: string-keyed objects, arrays, null, booleans, integers, strings and finite Decimal
fractions. Decimal values become normalized exact strings without binary-float conversion:
zero is `"0"`, trailing fractional zeroes are removed, integer Decimals remain exact strings and
high precision is preserved. Existing JSON primitives are unchanged. Non-string object keys,
non-finite Decimals and arbitrary runtime objects fail closed with the stable typed ingestion
error and no provider body disclosure.

Canonical JSON and semantic hashes are order-independent and stable for equivalent Decimal text
forms. Existing integer-only game-settings hashes remain unchanged, and manual-file and
direct-memory compilation have identical game-settings semantics. The parser and repository-wide
canonical serializer remain untouched.

Acceptance requires focused and affected regressions, branch coverage and static gates; real
Windows/Python 3.13 bootstrap and fixtures reads through `DirectFplClient`; successful
`CurrentFplInputBundle` compilation; public-first snapshot progression beyond current-input
assembly; installed-wheel, repository and secret checks; a pushed isolated branch; and exact
final-SHA CI success. No real response body, runtime entry identifier or credential may be
retained.
