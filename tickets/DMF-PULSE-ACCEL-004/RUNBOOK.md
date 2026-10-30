# Wave004 operator runbook

Use the reviewed installed wheel environment for these commands. The source
checkout and installed wheel have separately recorded implementation fingerprints
because the wheel includes explicit configuration resources. An enrollment must
bind the actual installed runtime, full wheel and native platform context.

## One-time secure setup

```powershell
dmf credentials set-odds-key
dmf credentials status
```

Enter the existing account key only at the hidden prompt. Setup validates
locally and makes no provider request. Windows Credential Manager keeps the
entry under the current Windows user. Future eligible runs resolve it inside
the worker after authorization, reservation, claim and live route checks.
The owner does not need to type the Odds key again after initial setup.

Explicit maintenance:

```powershell
dmf credentials set-odds-key --replace
dmf credentials delete-odds-key
```

FPL is separate. When an authorized short-lived token is needed:

```powershell
dmf credentials set-fpl-token --expires-at <actual-aware-expiry>
dmf credentials set-fpl-token --replace --expires-at <actual-aware-expiry>
```

Supply its actual expiry; do not invent a TTL. No renewal, browser/session
extraction or refresh token is implemented. FPL expiry never changes the Odds
slot. Status prints configuration booleans only. Never pass either secret as an
argument or save it in a file. If hidden input is unavailable, setup refuses.
Backend selection and Linux session/systemd alternatives are in CREDENTIALS.md.

## Available now

```powershell
dmf dashboard
dmf dashboard --current-demo
dmf operation status
dmf forecasts inventory
dmf forecasts verify --artifact <explicit-public-forecast-path>
dmf player-evidence wyscout-demo
dmf player-lab proposal
```

The default dashboard opens without a credential lookup and reports the missing
live approval. `--current-demo` exercises the actual worker/models with owned
synthetic inputs. It is not a real recommendation. Use the pairing code printed
locally; it is not retained in browser evidence. Passive operation status queries
neither the vault nor DB. The explicit `operation status --check-credentials`
option inspects local presence metadata only and grants no source permission.

Recovery verifies exact bytes without parsing unknown JSON/pickle, regenerating
P01, freezing a cohort or reading a provider. Its ten-family catalogue separates
P01 match evidence from player cohorts and synthetic/reconstructed/unverified
families. Missing real accuracy remains unavailable. The owned formation demo
is not downloaded real Wyscout data and all unsupported minutes stay unknown.

## Live enrollment and future startup

Complete the existing-account draft in PILOT-DRAFT-PACKAGE-BOUND.json using
nonsecret account/plan/dated-credit evidence, exact manager and official deadline,
source/purpose/retention permissions and canonical control receipt. Its proposed
Odds scope is one manually triggered EPL sport-wide GET, UK h2h+totals, one
request/two credits, zero automatic retries and conservative spent reservation
on failure. Proposed day and period caps are one request/two credits, requiring
actual owner and plan approval. No balance or entitlement is inferred from a key.

The engineering reference wheel is unenrolled. After a complete independent
review, a new reviewed wheel must carry the approved row in the existing fixed
registry. Rebind its final full wheel/resource identities in the authority
package; a runtime draft JSON cannot enroll itself. Follow OPERATION.md for
explicit PostgreSQL setup, immutable receipts, recovery and deployment. Never
initialize a replacement history to reset usage. Control metadata retention
permission is separate from provider and forecast retention.

Once that exact installed enrollment is eligible:

```powershell
dmf operation validate-installed --refresh-approval <installed-id> --entry-id <id> --horizon 1
dmf dashboard --refresh-approval <installed-id> --entry-id <id> --deadline-at <qualified-aware-deadline>
dmf pulse --refresh-approval <installed-id> --entry-id <id> --horizon-gameweeks 1
```

These reuse the same authorizer, PostgreSQL ledger, process worker and final
publication checks. The console derives its deadline from the trusted row.
There is no repeated Odds prompt or second grant system. Typed messages identify
missing/corrupt credentials, expired FPL tokens, stale quota, spent attempts,
revocation, deadline and control recovery actions. A failed/expired run publishes
no recommendation and does not refund attempts or conservative reservations.

## Outstanding decisions

- Qualify the existing account's nonsecret plan and remaining-credit evidence;
  approve the exact manager/routes/purpose/window and proposed bounded pilot.
- Permit and configure canonical control metadata separately. Complete any
  required source retention/evaluation permissions before a real cohort is kept.
- Resolve P01's exact historical-code/no-regeneration conflict by an explicit
  reviewed nongenerative canonical code binding before any reassessment. The
  conditional five-GET plan in EVALUATION-READINESS.md is not permission. A02/A03
  stay consumed; the display-name candidate stays inactive.
- Supply an additional approved artifact/folder locator if the reported other
  real freezes lie outside the bounded inventory. Do not send credentials.
- Technical acceptance and any later production activation remain separate;
  no production activation or model promotion occurs in this programme.
