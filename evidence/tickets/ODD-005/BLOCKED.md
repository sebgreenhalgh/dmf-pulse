# ODD-005 blocker: frozen decimal-string contradiction

Status: **RESOLVED BY PACK 1.1**

Recorded: 2026-07-25

Resolved: 2026-08-02

## Authority resolution

Corrected Pack 1.1 freezes source-scale public serialization and separate
numeric semantic hashing. Its market-observation schema accepts `"1.80"`,
validates numeric value strictly greater than one, and retains the golden
outputs unchanged. The corrected schema SHA-256 is
`be1e753ad192368fbd8a2b82383cd86e07be2104ba5595e1ea81b5581144f217`;
the Pack 1.1 manifest SHA-256 is
`c030d775f2c4f5f68910ef443b1f0a86bc2a6e096299d448fbc0d81d48a62a20`.

The material below is retained as the exact historical Pack 1.0 stop evidence.

## Mandatory stop condition

`19_STOP_AND_EXCLUSION_CONTRACT.md` requires an immediate stop when a golden
output contradicts another frozen contract. `16_TEST_FIXTURE_ORACLE_CONTRACT.md`
states that the golden outputs define the exact decimal strings and that Codex
may not overwrite them to match the implementation.

## Exact conflict

The frozen public contract at
`public_contracts/market_observation.schema.json:18` has SHA-256
`bca7e220088e8e2005903caed7809ec2a2faba8d623328190c5abb4c2428f66c` and
defines this pattern for `decimal_odds`:

```text
^(?:1(?:\.\d*[1-9])?|[2-9]\d*(?:\.\d+)?|1\d+(?:\.\d+)?)$
```

That pattern rejects `"1.80"` because the fractional part of a value beginning
with `1` must end in `1` through `9`. It also accepts `"1"`, although the
domain and database contracts require decimal odds to be greater than 1.

Two frozen golden outputs require the rejected exact string:

- `fixtures/odds/ODD-005/expected_outputs/happy_path.json:12`, SHA-256
  `05d16722d6027822d3e03bff3cdeb56bcf475600b033c18820e4d1f027b619d7`,
  requires `book_alpha.HOME` to be `"1.80"`.
- `fixtures/odds/ODD-005/expected_outputs/as_of_2026-08-20T12-05-00Z.json:6`,
  SHA-256
  `015a3180323a06aa9a09e99ffb90c00a1e411d819a3c51d1ac927843086ede73`,
  requires `book_alpha.HOME` to be `"1.80"`.

Preserving the source scale satisfies the golden oracles but produces output
invalid under the frozen public schema. Canonicalizing the same exact numeric
value to `"1.8"` satisfies the schema but violates both exact golden outputs.
Neither frozen artifact is authorized for implementation-time modification.

## Required authority resolution

Provide a revised, hash-consistent context pack that does one of the following
and explicitly freezes the intended lexical Decimal policy:

1. updates the public-schema pattern to accept the required source-scale
   strings while still rejecting values less than or equal to 1; or
2. updates the golden exact strings to the canonical representation accepted by
   the public schema.

The pack manifest and detached checksum ledger must be revised with whichever
artifact changes.

## Stop state

- The literal 28-command acceptance sequence was not run after discovery.
- No completion commit was created.
- `review_pack/ODD-005/DMF_PULSE_ODD-005_REVIEW.zip` was not created or claimed.
- The current uncommitted implementation and tests remain intact for resumption.
- No live FPL, The Odds API, or other provider request was made, and no real API
  key was requested, read, or stored.
