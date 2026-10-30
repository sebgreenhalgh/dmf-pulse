# Operator setup, reviewed enrollment and recovery

This slice uses the accepted RefreshAuthorizer, the fixed installed production
enrollment resource, CurrentRefreshSession, DeskRuntime and its normal process
worker. It introduces no provider permission, quota probe, dataset acquisition,
parallel grant scheme, model parameter or production activation.

`operation status` is pure metadata composition by default. All eight stages are
`NOT_CHECKED`: ENGINEERING_READY, CREDENTIALS_CONFIGURED,
ACCOUNT_ENTITLEMENT_VERIFIED, PROJECT_RIGHTS_APPROVED, CONTROL_LEDGER_READY,
LIVE_PILOT_AUTHORIZED, LIVE_PILOT_EXECUTED and PRODUCTION_ACTIVE. The optional
explicit `--check-credentials` calls the credential service's presence interface.
It can verify credential presence only. It never contacts a provider, decodes a
key itself, verifies an account plan or grants project rights. Dashboard opening
and automatic status refresh must not invoke this option/interface.

## Complete operator route

1. Run `dmf operation prepare-pilot --authorization-id ACCEL004-PILOT-<fresh-id>
   --output <new-owner-package.json>`. This writes a create-only, semantically
   authenticated review draft. Unknown account, plan, owner, source scopes,
   manager, cutoff/deadline, code, wheel and canonical control evidence remain
   explicit blockers. `PilotProposal`/`write_metadata` is the typed Python seam
   for supplying separately obtained redacted metadata through `--proposal`.
   A complete draft is ready for independent owner review, never for execution.
2. Supply the exact account entitlement/plan and remaining-credit evidence with
   observation/reset timestamps, project-purpose/source rights, manager-bound
   routes, official decision deadline, exact package implementation fingerprint,
   full wheel hash, fresh owner approval and independent review. Key possession
   establishes none of these. The historical consumed team-strength approvals
   cannot supply the pilot identifier.
3. Explicitly permit control metadata and run `prepare-control --account-ref
   <opaque-id> --operator-ref <opaque-id> --control-evidence <sha256>
   --approve-control-metadata --output <setup.json>`. This command has no DB or
   provider I/O. `--owned-synthetic` selects only the isolated synthetic database
   identifier. Provider credentials and connection URLs are not accepted fields.
4. Run `init-control --request <setup.json> --output <new-receipt.json>` against
   an already configured/migrated canonical PostgreSQL control database. The
   existing initializer chooses a random ledger identity on first setup and
   reopens the canonical account history on subsequent setup. The operator
   cannot select a fresh identity to reset an account budget. This is explicit
   control administration, not acquisition permission. No migration, connection
   lookup or initialization occurs when opening the dashboard.
5. A maintainer independently reviews the complete authority package and builds
   a new reviewed wheel containing the exact approved row in the existing fixed
   `dashboard/resources/production_refresh_enrollments.json`. The packaged row
   uses the existing strict OperatorRefreshApproval contract; its source scopes,
   account, plan period, caps, code fingerprint, manager routes, deadline and
   canonical ledger must agree with the reviewed evidence. Detached review binds
   the resource byte hash and full wheel. The executable fingerprint excludes
   that one resource to avoid self-reference. Installation/deployment of this
   reviewed wheel uses the ordinary package manager. A runtime document, path,
   environment value or draft package cannot enroll a row. The installed registry
   remains empty unless this separate authority and deployment actually occur.
6. Run `validate-installed --refresh-approval <installed-id> --entry-id <id>
   --horizon 1`. This calls the current session's same request builder and
   RefreshAuthorizer.preflight. Code/profile/manager/routes, approval freshness,
   exact qualified deadline, quota freshness, one-shot consumption and account
   daily/monthly reservations are checked under the existing authenticated SQL
   lock. It appends no reservation/claim/check/attempt and reads no credentials.
   The preview is an observation; actual Refresh repeats every check atomically.
7. Only a separately eligible live pilot may use the enrolled console/dashboard
   path. `operation.console.run_enrolled_current` resolves the installed approval
   and its deadline, uses the same current session and DeskRuntime process worker,
   publishes once through runtime.view after the existing custody/expiry checks,
   and closes the runtime/child on success, failure or interruption. The root
   pulse CLI delegates here. There is no automatic retry or alternate optimizer.

The proposed pilot is one manually triggered one-GW MARKET_PRIMARY run. Its Odds
scope is one sport-wide GET `/v4/sports/soccer_epl/odds`, `regions=uk`,
`markets=h2h,totals`, maximum one request/two reserved credits and zero automatic
retries. Proposed day/period caps are one request/two credits; actual owner and
plan evidence must approve these caps. Provider-returned empty data or failure
does not refund the canonical conservative reservation. No source permission or
consumption state changes merely because a draft is complete.

## Recovery and boundaries

Use `prepare-control` with `--ledger-id <existing-id>` to create a recovery
request, then `recover-control --request <request.json> --output <new-receipt.json>`.
Recovery only constructs and audits an existing PostgresUsageLedger. It never
calls initialize, appends a record, chooses a new identity, clears a consumed
one-shot or resets a day/month budget. Missing history, wrong account/identity,
schema/UTC mismatch, hash-chain corruption and unavailable DB fail closed.
PRIVATE_CURRENT cannot select SYNTHETIC_TEST_DATABASE, including through a
constructed-model bypass, before any connection factory is called. Receipt
hashes attest metadata integrity, not provider rights. Canonical PostgreSQL
administration/backups remain trusted infrastructure; wholesale replacement of
an entire database by its owner is not made detectable by an unkeyed hash chain.

Authenticated ledger audits contain only identifiers, counts, control timestamps
and chain hashes. ATTEMPT is evidence of an attempted route, not a completed
recommendation. This slice does not infer LIVE_PILOT_EXECUTED from ledger events
or from owned synthetic output, and never marks PRODUCTION_ACTIVE verified.

No live account, DB, credential value, provider/quota call or purchase was used
to implement this tooling. Automated tests inject owned metadata/vault interfaces
and run the accepted current worker on repository-owned synthetic sources.

## Primary public source notes

Reviewed 2026-10-30: [Odds V4 documentation](https://the-odds-api.com/liveapi/guides/v4/)
documents the sport-wide odds endpoint and the cost product of markets and
regions. Two markets in one region motivate the existing two-credit reservation.
[Provider terms](https://the-odds-api.com/terms-and-conditions.html), displayed
updated 2026-08-31, discuss private storage, derived analytics and prohibited
standalone feed resale. These general terms do not establish this account's
entitlement or activate project retention/source profiles. No account or quota
endpoint was queried. Exact account, plan, owner and project evidence remains
required for the separately reviewed installed enrollment.
