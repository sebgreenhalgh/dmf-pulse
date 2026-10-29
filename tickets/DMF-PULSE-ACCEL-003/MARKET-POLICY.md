# ACCEL-003 market authorization candidate

The fixed packaged production approval registry is empty. This programme enrolls no account,
approves no recurring acquisition and authorizes no live pilot. The new proposed
JSON is deliberately incompatible with an approved runtime contract: unresolved
account, plan, budget, identity and approval fields are null and its status is
`PROPOSED_INACTIVE`. Runtime JSON, environment variables and browser payloads
cannot enroll production approvals. `production_approvals()` reads only
`dashboard/resources/production_refresh_enrollments.json` on explicit invocation;
it exposes no path or environment override. Its schema, size, unique identities,
strict approval contracts and private classification are checked fail closed.

The executable content fingerprint excludes only that exact enrollment metadata
resource, preserving all authorization code and all other resources. Otherwise an
enrollment row containing its expected implementation identity would hash itself.
Trusted installation authenticates packaged metadata as it does packaged code;
this assumes the installed wheel/package has passed release review. Detached
release/pilot evidence must bind the final Git SHA, complete wheel SHA,
implementation content fingerprint and enrollment-resource byte digest together.
The wheel and Git hashes cannot be embedded inside their own bytes. The grant
independently binds the exact canonical enrollment row and source-profile hashes.

The public [terms](https://the-odds-api.com/terms-and-conditions.html), updated
31 August 2026, support this vendor-level use case. The account, plan, project
purpose, source profiles, reviewed implementation and runtime authorization
remain separate requirements. The previous L8 rights purpose is consumed and
unchanged. Public documents were retrieved at 2026-10-29T18:44:56Z; that is the
UTC clock checkpoint immediately after the combined HTML retrieval. No account,
provider API/JSON endpoint or credential was inspected.

The existing client sends one sport-wide EPL request with UK `h2h,totals`, decimal
odds and ISO dates. The [v4 guide](https://the-odds-api.com/liveapi/guides/v4/)
charges two requested markets times one region: reserve **one attempt and two
credits** for either one or three GWs. Horizon filtering does not require one
request per fixture. Bookmaker coverage is availability-dependent; later-GW
markets are not guaranteed. No sports/events/history/quota-check route is added.
The public Starter offer's 500 credits is not verified account entitlement.

`OperatorRefreshApproval` requires an exact source/account/profile hash and
route/call budget for FPL, Odds and OpenFootball; operator, purpose, season,
horizon and mode; qualified account plan/quota/terms evidence; reviewed code
identity; approval identity and finite validity; explicit daily/monthly request
and credit caps; reserve, freshness and acquisition/run windows; and permission
for secret-free control metadata. There are no runtime default daily/monthly
caps. Missing fields cannot authorize. Qualified quota evidence must match the
approved account and reset interval, remain fresh, and leave two credits after
the reserve and conservative unconfirmed usage.

The `implementation_sha` field is a 40-hex **implementation identity**, resolved
by the application from package content. It must not be accepted from a browser,
environment assertion or mutable checkout name. Future approval evidence must
name the final Git SHA **and** installed wheel/package content fingerprint;
these are distinct identities. Exact resolved rights-profile hashes and review
receipt identities must also match. This release's empty registry cannot be
populated merely by filling out the proposal.

`RefreshAuthorizer.authorize(request)` checks trusted enrollment and exact scope
before reserving, before worker creation, and before credential resolution.
`for_owned_sources` can inject only an `OWNED_SYNTHETIC` approval whose every
source is `REPOSITORY_OWNED_SYNTHETIC`. Such a grant is never real execution
authority: the worker must require injected owned transports and forbid default
real transports for that classification.

`UsageLedger` holds the shared scope, issuance, grant, consumption and budget
policies. Its transaction/append hooks require atomic durable storage and fully
authenticated event rows. The canonical production backend is PostgreSQL under
accepted ADR-DATA-002. Approval and grant both bind their exact `ledger_backend`
and ledger identity. A storage adapter cannot broaden the shared policy.

`DurableUsageLedger` is an **owned-synthetic JSON engineering backend** and
unconditionally refuses `PRIVATE_CURRENT`; a source/owner approval cannot make
it canonical production control state. `DurableUsageLedger.create(path)` is
explicit first-time setup and generates a
new identity; it never recreates an existing or missing history automatically.
An enrolled approval is bound to that identity. Reservations use exclusive
locking, create-only hash-chained records and file flush/fsync. Cross-process
workers reopen the same identity, claim a reservation exactly once, and verify
the complete grant digest before any factories or credentials. Every delegate
send must first call `attempt` with the exact provider/method/host/path. Claims,
checks and attempts enforce expiry and a durable monotone UTC clock; acquisition
must finish before the information cutoff.

Reserve one request and two credits before starting the worker. Startup failure,
cancellation, transport failure, timeout or 429 does not refund that reservation.
Each actual route attempt is also counted durably before its delegate. The new
client injection seam can pass the exact approved profile, known quota and
`maximum_attempts=1`; legacy construction retains its accepted behavior.
The existing total 30-second provider deadline remains. No automatic retry is
proposed. A later manual trigger needs eligible authority, budget and any
owner-approved cooldown. Invalid quota headers remain a fail-closed source
failure; no optimistic quota estimate is invented.

The ledger stores only opaque random ids, hashes, UTC control times, reset/day
keys and operation kinds. It writes no manager state, player/market values,
source bodies, credentials, account names or browser state. Local control
directory protection is part of trusted operator/OS setup. Crash-left locks or
partial records block; they are not automatically cleared. Hash chains detect
corruption and grant modification, but do not defend against a privileged
operator deliberately replacing an entire disk history. Recovery requires a
separate reviewed reconciliation and owner action, never a reset button.

Before a real profile can be enrolled, a qualified canonical PostgreSQL control
backend and the independently reviewed full worker path must be in place. The
owner checklist must resolve all
null proposal fields, verify exact plan allocation and other account use, set
explicit daily/monthly caps and quota freshness, approve the control ledger and
its custody/recovery, bind final reviewed code and source profiles, set expiry,
and separately authorize the exact pilot. FPL and retained evaluation rights
remain independent. Any retained Odds research needs a separate source/purpose
profile; vendor-permitted training does not change this transient proposal.

Acceptance covers empty production enrollment, wrong code/review/operator/
season/account/profile/routes, revoked/expired authority, stale/missing quota,
deadline windows, consumed grants across restart, exact route caps, daily and
monthly limits, concurrent reservations, tampered/relabelled grants, wrong
workers, corruption/crash locks, control-record disclosure and injected-client
rights/quota ordering. All tests use owned sources with network blocked.
