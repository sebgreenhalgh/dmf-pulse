# NRM-006 blocker: frozen retry fixture contradicts inherited quota contract

Status: **BLOCKED**

Recorded: 2026-08-06

## Mandatory stop condition

`18_STOP_AND_EXCLUSION_CONTRACT.md:3-7` requires an immediate stop and this
blocker record when a golden output conflicts with another frozen contract.
It also forbids modifying frozen fixtures/oracles to make tests pass
(`18_STOP_AND_EXCLUSION_CONTRACT.md:16`).

The Pack 006 fixture/oracle contract independently states that supplied
fixtures and expected outputs are frozen and may not be overwritten to match
the implementation (`15_TEST_FIXTURE_ORACLE_CONTRACT.md:3`).

## Preflight evidence

- Required branch: `stage/A6/NRM-006-odds-normalisation`.
- Required and observed HEAD: `e36ea84cda9e80191a9160d037f8e7035477b9b1`.
- The repository was clean before preflight; no implementation file was
  changed.
- Pack manifest and detached checksums validated with zero errors: 79 declared
  manifest entries, 79 validated entries, 80 detached checksums, and 81 actual
  pack files. `23_PACK_MANIFEST.json` SHA-256:
  `4267d3137bca3e625718953cbb48ab6b85e69dd3b0f51227b672868599e31b3b`.
- Docker Desktop 4.83.0, Docker Engine 29.6.2, and Docker Compose 5.3.1 were
  available. The pinned container reported PostgreSQL 18.4
  (`Debian 18.4-1.pgdg13+2`).
- Alembic reported the single required head `20260725_0004`; a fresh disposable
  test volume was upgraded through that head.
- The inherited baseline passed offline against PostgreSQL: `882 passed in
  139.46s`, with zero skips.
- No live FPL, The Odds API, or other provider request was made. No real API
  key was requested, read, or stored.

## Exact frozen-contract conflict

The frozen input fixture
`fixtures/odds/NRM-006/rate_limit_retry.json` (SHA-256
`1d2c5377a9dda98facc58469f34c051b6f105a477c171bf4c58a2b7cabc0278d`)
defines two fake HTTP responses:

1. a 429 response containing `Retry-After`, `x-requests-remaining`, and
   `x-requests-used`, but no `x-requests-last`;
2. a 200 response containing `x-requests-remaining` and `x-requests-used`, but
   no `x-requests-last`.

Its frozen expected output, `expected_outputs/rate_limit_retry.json` (SHA-256
`72431b449f943b3980cea059a98201c92e38b4f9f315de245b3aa1bcd0291fd6`),
requires two transport calls, one injected two-second sleeper call, no real
sleep, and final status `COMPLETE`.

The inherited frozen ODD-005 credential/HTTP/quota contract (SHA-256
`b2ed3c0cf73e50f5f82288847b0f1a95054d42305d3260a37a045d157281f204`)
requires capture of all three provider quota response headers, including
`x-requests-last` (`authority/odd005_contracts/09_CREDENTIAL_HTTP_AND_QUOTA_CONTRACT.md:43-50`),
and prohibits invented account evidence.

That requirement is implemented and explicitly protected by the inherited
baseline:

- `src/dmf_pulse/ingestion/odds/client.py:348-363` parses all three quota
  headers;
- `src/dmf_pulse/ingestion/odds/client.py:437-449` classifies a partial required
  header set as `INVALID`;
- `src/dmf_pulse/ingestion/odds/client.py:476-478` rejects a nominal 200
  response whose required quota evidence is invalid;
- `tests/unit/ingestion/test_odds_foundation.py:677-704` requires a partial
  quota-header response to fail as non-retryable `SOURCE_UNAVAILABLE` with
  `quota_header_state == "INVALID"`.

Therefore the frozen second response cannot truthfully produce `COMPLETE`.
Treating it as successful would weaken the inherited quota contract and test;
supplying `x-requests-last` in a fake transport despite its absence from the
frozen response would fabricate provider evidence; and editing the fixture or
oracle is expressly forbidden. No implementation can satisfy all of these
frozen requirements simultaneously.

## Required authority resolution

Provide a revised, hash-consistent Pack 006 that does one of the following:

1. adds an explicit `x-requests-last` value to the frozen successful response
   (and preferably to every response intended to carry valid quota evidence),
   then updates the fixture manifest, pack manifest, and detached checksum
   ledger; or
2. explicitly supersedes the inherited three-header quota rule and defines the
   truthful semantics, persistence, and validation behavior for partial quota
   response headers.

## Additional temporal clarification requested

The inherited observation contract makes a quote usable only after its
canonical transaction commits, while the compact NRM-006 temporal contract
samples `publication_at` before work and persists it in the final transaction.
For a cutoff between that sample and the actual commit, the proposed timestamp
can qualify a row that was not yet transactionally visible. A corrected pack
should state whether `publication_at` is a logical in-transaction timestamp or
must be tied to actual commit visibility so the inherited no-look-ahead rule
has one implementable meaning.

## Stop state

- `evidence/tickets/NRM-006/PLAN.md` was not created because preflight did not
  clear every required gate.
- NRM-006 implementation was not started.
- The literal 32-command acceptance sequence was not run after discovery.
- No completion commit was created.
- `review_pack/NRM-006/DMF_PULSE_NRM-006_REVIEW.zip` was not created or claimed.

