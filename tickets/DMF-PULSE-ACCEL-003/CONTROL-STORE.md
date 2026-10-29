# Canonical PostgreSQL refresh-control custody

Accepted DMFP-20 ADR-DATA-002 makes PostgreSQL authoritative for operational and
control-plane state. The private-current refresh implementation uses that accepted
architecture. The owned local JSON control backend remains a synthetic engineering
fixture and categorically rejects `PRIVATE_CURRENT`. No architecture exception,
provider entitlement or source-profile activation is introduced.

`PostgresUsageLedger` subclasses the shared `UsageLedger`. The same reviewed
reservation, one-shot consumption, quota, account/source/purpose/code scope,
issuance/freshness/deadline, grant claim and route-attempt policies apply to both
backends. PostgreSQL supplies atomic transaction and append hooks; it does not
duplicate or relax authorization policy. Approval and grant bind the `POSTGRES`
backend discriminator. Default production enrollment remains empty.
Private-current reserve/claim/check/attempt also require the operator database
reference; the synthetic test database selector fails before its factory.

## Explicit setup and ordinary operation

The constructor performs no reads, connections, environment access, source
acquisition or writes:

```python
ledger = PostgresUsageLedger(
    connection_factory,
    enrolled_ledger_id,
    account_ref=enrolled_account_ref,
    database_ref="OPERATOR_CONTROL_DATABASE",
)
```

`connection_factory` returns a context manager yielding an unbegun SQLAlchemy
Connection. The parent/worker resolves it server-side only after authority checks.
The backend does not accept or serialize a database URL, credential or engine.
`database_ref` is restricted to `OPERATOR_CONTROL_DATABASE` or
`SYNTHETIC_TEST_DATABASE`. Neither reference grants access or enrollment.

Initialization is separate, explicit setup after migration:

```python
ledger = PostgresUsageLedger.initialize(
    connection_factory,
    account_ref=enrolled_account_ref,
    database_ref="OPERATOR_CONTROL_DATABASE",
)
```

Initialization creates a random ledger identity only for a previously unseen
canonical account hash. A repeated call returns and authenticates the existing
identity and complete history. It never replaces or clears them. Ordinary refresh
does not initialize a missing ledger. Another ledger ID for the same account is
rejected; another account with that ledger is rejected. New approvals still count
the account's prior reservations in daily/monthly quotas. A consumed one-shot
remains consumed after reopening, worker restart or browser reload.

The qualified database and account reference are trusted control configuration.
Pointing at another database is not a quota-reset interface: normal operation
requires the already enrolled immutable ledger identity and binding. Replacing
the canonical database, its complete backup, code enrollment or privileged database
schema is an owner/DBA trust-boundary change, not an authorized runtime action.
Recovery must preserve the existing identity and every reservation; fail closed
when those cannot be authenticated.

## Atomicity, durability and integrity

Migration `20261029_0008` extends existing `core` with two tables and seeds no
approvals or provider records:

- `refresh_control_ledger`: unique canonical account hash, ledger ID, version and
  authenticated binding hash.
- `refresh_control_event`: exact sequence, event kind/time, previous/current SHA
  and bounded control-only payload.

Each operation starts a transaction, validates exact schema head/UTC/fsync, sets
synchronous commit, acquires an account advisory transaction lock and locks the
canonical ledger row. It authenticates the binding and the full chronological
event chain before the shared policy sees records. Policy decision and append
commit under the same lock. Failed transactions roll back completely; successful
reservation commits before worker/provider execution. A completed reservation is
never refunded merely because execution later fails, cancels or crashes.

Unique keys and SQL insert guards independently enforce canonical account
binding, exact sequential hash-chain/time identity, reservation uniqueness and
claim-before-attempt/check relations. Concurrent reserve/claim/attempt operations
serialize. UPDATE, DELETE and TRUNCATE reject on both tables. A privileged test
that bypasses an update trigger still produces an invalid authenticated history
and the next ordinary operation fails closed. Hash chains do not make a
malicious DBA or wholesale database replacement trustworthy.

Lock and statement waits are bounded at five/ten seconds. Each ledger holds at
most 100,000 events and each payload at most 4,096 bytes. Capacity, unavailable DB,
invalid schema/identity, clock regression, corruption and SQL failures block
execution with bounded typed errors. No exception includes a DSN or provider body.

## Persisted fields and rights boundary

The exact allowed event schema contains kind/time/reservation ID and hash-chain
identity. Reservations additionally contain grant/approval/account/authorization
hashes, UTC day and qualified quota period. Claims contain only a worker hash;
attempts contain only a route hash; checks add no source facts. Unknown fields,
null/malformed hashes, private payloads, arbitrary strings, noninteger sequences
and mismatched column/payload identities reject in Python and SQL.

No FPL player/catalogue/fixture/price/manager facts, forecast, point labels,
provider response, market prices, source JSON, raw approval document, account
credential or database credential can be stored in this schema. Control-metadata
retention approval remains an explicit approval requirement. Existing private
FPL raw/derived/cache/backup/training denials and the player research registry are
unchanged. An internal owner decision does not grant provider rights.

Normal production enrollment is still empty. Forged `PRIVATE_CURRENT` grants fail
the shared enrollment validation before even the injected PostgreSQL factory is
called. The PostgreSQL backend demonstrates engineering readiness only; it cannot
authorize a live source/account/route/request budget/purpose/code pilot.

## Acceptance and migration compatibility

Owned synthetic integration exercises reserve/claim/check/attempt, reopen,
canonical-account identity, one-shot reuse, concurrent requests/claims/attempts,
atomic rollback, SQL update/delete/truncate denial, extra/private/null field
attacks, wrong hash/previous/time/replay attacks and privileged-test corruption.
It also proves a forged private-current grant invokes zero connection factories.
No real provider request or credential is used.

Doctor now requires the exact `canonical_refresh_control` capability. Existing
metadata, schema hash, head-specific ingestion, installed-wheel capability and
linear migration tests bind the new head exactly. Historical migration contents
and numerical policies remain unchanged. Integration cleanup preserves append-only
control history and uses unique owned accounts; separate tests explicitly prove
that TRUNCATE is rejected rather than disabling its guard for test convenience.
Ordinary data/rights/custody cleanup and all previous tests remain required.

Exact head catalog SHA-256:
`473c88f0e9afe0d29673fe4d644d11740958c357c98b4d3e8029d033be381a2f`.
The predecessor `0007` catalog remains
`b29b0e3f3f3e2ff99ef62693c5bb9f4e6344805248a7e25807f29f4bcb5d2417`.
Downgrade/re-upgrade is a separately invoked synthetic acceptance procedure and
does not authorize deleting real retained control history.
