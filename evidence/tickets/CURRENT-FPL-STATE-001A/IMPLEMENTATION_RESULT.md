# CURRENT-FPL-STATE-001A implementation result

Status: **IMPLEMENTED PENDING INDEPENDENT REVIEW**.

The implementation starts at immutable parent
`2bc2783adc37d0956962d7574f73cbb6af711e28` on branch
`integration/current-fpl/CURRENT-FPL-STATE-001A-manual-transient`. It manually reconciles only the
reviewed donor capability and does not merge the donor history.

## Implemented capability

- `CurrentFplInputService` accepts two operator-owned local files plus explicit competition,
  season, target Gameweek, capture time, cutoff, and rights profile metadata.
- Both sources pass a bounded regular-file gate and the current-main FPL parser. The compiler has
  no transport, database, persistence, cache, backup, or artifact-write dependency.
- The private result contains immutable typed team, position, player, event, fixture, game-setting,
  provenance, rights, and quality contracts with season-scoped provider identities.
- The target event is never inferred. It must be exactly present, unfinished, officially current
  or next, and have at least one resolvable fixture with kickoff after its official deadline.
- Cross-resource identifiers, canonical positions, prices, fixture competitors/events, current
  and next state, source times, availability timestamps, provider bounds, and approved rights all
  fail closed.
- `dmf ingest fpl current validate` prints only a disclosure-minimized JSON summary. Names, news,
  paths, source bodies, credentials, and database references are absent.

## Verification checkpoint

- Focused current-FPL/compiler/CLI: 57 passed.
- Entire new compiler module: 90.30% branch-aware coverage (477/509 statements and 100/130
  branches covered); canonical JSON report in `coverage.json`.
- Inherited parser/config/client/service/CLI/security/contract/property matrix: 205 passed.
- Inherited PostgreSQL FPL retention/persistence matrix after canonical migrations: 68 passed.
- Frozen sync, repository-wide format/lint/strict typing, build, canonical clean-wheel, ODD-005
  wheel, GCS-008 wheel, repository validation, and secret scan all passed.
- The isolated installed wheel executed the full public current-FPL command outside the source
  tree against temporary synthetic GW2 inputs and returned a valid safe summary; the temporary
  inputs were deleted with the isolated process.
- No real official-FPL or other provider network call was made; no credential was read; no
  operator payload was added to the repository.

Exact commands and outcomes are recorded in `COMMAND_LEDGER.txt` and `result.json`.
