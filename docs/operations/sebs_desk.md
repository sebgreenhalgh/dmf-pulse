# Seb's Desk

Start from a Python 3.13 checkout with `uv sync --all-groups --frozen`, then:

```powershell
uv run --frozen dmf dashboard --demo
```

Open `http://127.0.0.1:8765` in your browser. Enter the one-time pairing code
displayed in the terminal. Click **Refresh Recommendations**. The synthetic demo
runs the actual private Stage 7/8/9/10/11 services with authenticated packaged
synthetic transports. It does not load a canned decision. Select one or three
Gameweeks before refreshing. Progress is visible while the disposable worker runs.

The synthetic catalogue has 121 players: 120 model projections and one explicitly
removed/unmapped player. These are test counts, not current-season facts. My Team
shows the actual model squad, XI, ordered bench, captain/vice, transfers and hold
comparison. Decisions shows evaluated frontier plans and paired outcome ranges.
Players supports search, sorting, fixture detail, all 13 scoring components,
PMFs, minutes assumptions, provenance and same-run/horizon comparison. Three-GW
player xPts is a sum of existing GW means; no marginal quantiles/probabilities
are combined into an invented horizon distribution.

Model Performance executes a separate analytic synthetic custody/outcome fixture
through the accepted Stage-12 kernels. It shows point/probability/distribution
diagnostics, calibration, cohort errors, a diagnostic zero baseline and a paired
chronological holdout. It is not historical validation of the recommendation
model. The real cohort status remains exactly:

`NO RIGHTS-QUALIFIED REAL PROSPECTIVE COHORT`

An installed wheel supports the same `dmf dashboard --demo` command without the
repository or test package. No Node build, cloud UI, account write or public
deployment is involved. `scripts/start_sebs_desk.ps1 -Demo` is a convenience
launcher for a checkout. Use `--port 8766` if the default port is occupied.

## Live access

`dmf dashboard` starts the private application with its real-data boundary.
Refresh currently returns `RIGHTS_BLOCKED_MARKET_REFRESH_NOT_APPROVED` before any
worker/provider/credential access. The accepted Odds profile is restricted to a
single earlier observation. This programme does not create recurring market
approval, a new FPL route entitlement, or retention rights. The existing
`PrivateV1OneCommandService` remains the integration used by the demo and the
future eligible private path; the source gate must be satisfied before live use.
See the programme's source/rights decision document for the concrete next steps.

## Lifetime and security

The listener binds literal `127.0.0.1` only. Host, client address, Origin and
cross-site/proxy headers are checked. The code is paired once, with at most five
attempts; authentication uses an HttpOnly SameSite=Strict cookie. Mutations
require exact Origin, JSON and a same-origin custom header. The session lasts
at most an hour. Responses are no-store, CSP-restricted and frame-denied.

Presentation is a single active in-process response view, with a maximum
15-minute lifetime and earlier official-deadline expiry. Every data publication
rechecks the existing authenticated actionability receipt and clock floor.
Supersession, failure, cancellation, expiry, sign-out and shutdown clear it.
Only one disposable computation process can run. Cancellation/timeout/shutdown
terminates and joins it. Failed cleanup preserves the handle and closes the
runtime permanently, preventing another worker.

The browser stores data only in memory/DOM. It clears on hiding/navigation,
aborts pending requests, rejects old job responses/errors and enforces a
remaining-lifetime timer. Reopening a tab revalidates with the server. No
localStorage, IndexedDB, service worker, provider token, generic proxy or browser
credential form exists. Source bodies and scenario matrices do not cross the
presentation boundary. Python/browser garbage collection is not a secure-memory
erasure guarantee. No atomic OS-clock-plus-network-write claim is made.

Press **Cancel & clear**, **Sign out**, or Ctrl+C to end work. After sign-out or
session expiry, restart the command to create a new pairing session. Do not save
private pages, responses, screenshots or browser profiles as research evidence.

## Evaluation custody and storage

Player forecasts carry exact season/player/GW/fixture keys, PMF/component means,
model/rules/input identities, generation/cutoff/deadline/finality times, source
vintages and retention classification. Publicly resealing a replacement does
not establish custody. Scoring verifies the original ledger record and the
preregistered experiment. The ledger clock cannot move backwards.

The closed registry admits exact owned synthetic forecast/label identities.
Borrowing a synthetic source reference cannot qualify a different forecast or
private Stage-9 output. The PostgreSQL ledger also enforces qualified sources,
immutable artifacts, predeclared cohorts, exact score pairs and append-only
corrections. It preserves the original label vintage of existing scorecards.
Real private FPL raw/derived persistence is denied before the connection factory.
Direct SQL cannot insert an invented source approval or private-derived artifact.

There is no qualified real source in this release. A later independently reviewed
source profile, registry version and migration is required before real research
retention. Adding that qualification does not require redesigning forecast,
label, metric, pair or UI contracts. No synthetic test promotes a model.
