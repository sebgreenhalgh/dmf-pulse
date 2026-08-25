# CURRENT-FPL-STATE-001A implementation result

Status: **REMEDIATED PENDING INDEPENDENT RE-REVIEW**.

The implementation starts at immutable parent
`2bc2783adc37d0956962d7574f73cbb6af711e28` on branch
`integration/current-fpl/CURRENT-FPL-STATE-001A-manual-transient`. It manually reconciles only the
reviewed donor capability and does not merge the donor history.

## Implemented capability

- `CurrentFplInputService` accepts two operator-owned local files plus explicit competition,
  season, target Gameweek, capture time, cutoff, and rights profile metadata.
- Both sources pass a descriptor-bound regular-file gate and the current-main FPL parser. Each path
  is checked before and after one low-level open; the opened descriptor is checked for regularity
  and identity, supplies the bounded bytes, and is always closed. The two opened objects must be
  distinct. The compiler has no transport, database, persistence, cache, backup, or artifact-write
  dependency.
- The private result contains immutable typed team, position, player, event, fixture, game-setting,
  provenance, rights, and quality contracts with season-scoped provider identities.
- The target event is never inferred. It must be exactly present, explicitly `finished=False`,
  explicitly not previous, and have exactly one explicit current/next flag; contradictory true
  flags on every event fail closed. It must have at least one resolvable fixture with kickoff after
  its official deadline.
- Cross-resource identifiers, canonical positions, prices, fixture competitors/events, current
  and next state, source times, availability timestamps, provider bounds, and approved rights all
  fail closed.
- `dmf ingest fpl current validate` prints only a disclosure-minimized JSON summary. Names, news,
  paths, source bodies, credentials, and database references are absent.

Independent review subsequently identified CFSA-REV-001/002 at reviewed head
`140100fa49bea1d3d0493cb68f186af564fa1380`; remediation is recorded in
`REVIEW_REMEDIATION.md`. No human acceptance is claimed.

## Remediation verification checkpoint

- Focused current-FPL/compiler/CLI: 76 passed.
- Entire new compiler module: 91.35% branch-aware aggregate coverage (519/550 statements and
  115/144 branches covered); canonical JSON report in `coverage.json`.
- Inherited parser/config/client/service/CLI/security/contract/property matrix: 205 passed.
- Inherited PostgreSQL FPL retention/persistence matrix after canonical migrations: 68 passed.
- Frozen sync, repository-wide format/lint/strict typing, build, canonical clean-wheel, ODD-005
  wheel, GCS-008 wheel, repository validation, and secret scan all passed.
- The isolated installed wheel executed the full public current-FPL command outside the source
  tree against temporary synthetic GW2 inputs and returned a valid safe summary; the temporary
  inputs were deleted with the isolated process.
- No real official-FPL or other provider network call was made; no credential was read; no
  operator payload was added to the repository.

Remediation validation repeated the exact inherited 205 non-database and 68 PostgreSQL-backed
tests (273 total), the three wheel gates, and an installed-wheel synthetic GW2 command. Local
static/build/security gates are green; the direct Windows `mypy` launcher was blocked before
execution by Application Control, while `python -m mypy` passed all 248 source files. Exact Linux
final-SHA CI remains mandatory.

Exact commands and outcomes are recorded in `COMMAND_LEDGER.txt` and `result.json`.
