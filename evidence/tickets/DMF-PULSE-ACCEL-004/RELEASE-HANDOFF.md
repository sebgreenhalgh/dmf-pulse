# Wave004 operator and evaluation handoff

This programme implements secure routine credential retrieval, bounded forecast
recovery, classified performance reporting, existing-ledger operator tools and an
additional owned player-evidence adapter. It grants no football-provider access,
live pilot, source retention, model promotion or production activation.

The source package is frozen at
`a250fc831d50eb6fff7c3a174c4603b713049390`. The full wheel SHA is
`903b36191582a8eb5da6e849baaa2214d86196915231a636f3071f4b9c60f7bf`.
Its 499 package members match that Git source and explicit Hatch configuration.
Source implementation fingerprint:
`6ed14deda717204e3ee83354af1132f523e4b690`.
Installed Windows implementation fingerprint:
`1e1e32d326d0600ebd8fa711e0ad999dbee93b32`.
The accepted fingerprint includes installed configuration and native Path
ordering; these contexts must not be interchanged. The full wheel hash is the
portable primary package identity. Later publication commits contain metadata
only and must independently preserve all package, verification, test and workflow
bytes. Exact final HEAD, remote equality, all twenty CI jobs, coverage, raw
artifact hashes and actual capped ZIP are sealed in the detached final publication
receipt after CI. This document does not predict an unrun commit's CI result.

## 1. Automatic credential setup

Run once in the installed Windows environment:

```powershell
dmf credentials set-odds-key
dmf credentials status
```

Enter the existing Odds account key only at the hidden prompt. Local validation
makes no provider call. The normal Windows backend is current-user Windows
Credential Manager through pinned BSD-3-Clause pywin32-ctypes 0.2.3, with lazy
imports and two exact provider slots. Persistence is across logons for the same
Windows user. No custom encryption or plaintext persistent fallback is added.
The dependency's published Python classifiers are not a Python3.13 certification;
native Python3.13 acceptance is separately demonstrated.

**Does the owner need to type the Odds API key again after initial setup? No.**
Eligible engine and dashboard runs resolve it automatically inside the authorized
worker, after rights, reservation, claim and current route checks. Opening the
dashboard or running demo/default operation status performs no vault lookup.
Windows AUTO selects the vault; an explicit environment selector is required for
the legacy session mechanism. Linux retains the accepted systemd mechanism and
documented explicit session fallback. Backend failure is typed and actionable.

Rotate with `dmf credentials set-odds-key --replace`; delete with
`dmf credentials delete-odds-key`. There is no show-key command. FPL has a separate
slot and `dmf credentials set-fpl-token --expires-at <actual-aware-expiry>`.
Its actual expiry is mandatory, including checks after blocking control work.
There is no renewal, session extraction or invented TTL. Expiring FPL does not
alter Odds credentials. Native FPL storage rejects tokens beyond the WinCred
limit; it never truncates them. Python memory erasure is not claimed.

Available now: `dmf dashboard`, `dmf dashboard --current-demo`,
`dmf operation status`, `dmf forecasts inventory`,
`dmf forecasts verify --artifact <explicit-local-public-forecast>` and
`dmf player-evidence wyscout-demo`. After separate eligible trusted enrollment:

```powershell
dmf dashboard --refresh-approval <installed-id> --entry-id <id> --deadline-at <qualified-aware-deadline>
dmf pulse --refresh-approval <installed-id> --entry-id <id> --horizon-gameweeks 1
```

The current reference wheel has an empty production registry. These future
commands require an independently reviewed enrolled wheel and exact package
rebinding. A JSON draft cannot enroll itself. The full setup, control initialization,
recovery and startup procedure is [RUNBOOK.md](../../../tickets/DMF-PULSE-ACCEL-004/RUNBOOK.md).

Security evidence covers injected unavailable/corrupt/wrong-context stores,
concurrency, denied lookup, quota/cutoff/revocation, safe exception graphs and
IPC/browser disclosure. Final native evidence uses a fresh owned synthetic
namespace, eight distinct hidden PowerShell processes and eight Python processes,
production resolver interfaces, rotation, deletion and verified absence. The
synthetic hidden-input shim is disclosed; no real account key or normal vault
entry was inspected. Installed current-mode/browser evidence uses owned inputs.

## 2. Recovered predictions

The bounded search considered 76 project roots and 78,801 entries, read 377
metadata bodies and inspected 191 archive central directories. It records 83
root/access/absence gaps and three archive gaps. Private artifact bodies remain
local. Unrelated folders, credentials and unknown pickle/JSON bodies were not
opened. Search limitations leave additional owner-reported freezes unresolved;
they do not establish absence.

The exact metadata and approved locators are in
[RECOVERY-INVENTORY.json](RECOVERY-INVENTORY.json),
[RECOVERY-METHOD.json](RECOVERY-METHOD.json) and
[FORECAST-RECOVERY.md](../../../tickets/DMF-PULSE-ACCEL-004/FORECAST-RECOVERY.md).
Each family remains separate:

| Family | Classification and population | Evaluation status |
| --- | --- | --- |
| P01 public match forecast | REAL_PRE_OUTCOME_FROZEN; ten 2026/27 fixtures, 10–12 October; three products each | Real match evidence; no admitted all-ten final labels |
| P01 October14 authentication/October16 fallback records | POST_OUTCOME metadata for the same original ten fixtures | No new forecast origin or additional sample |
| Historical private live-operation families | UNVERIFIED_CUSTODY; private decisions/observation metadata | Retained forecast values and all upstream evaluation rights unqualified |
| ACCEL001 controlled private-pipeline decisions | SYNTHETIC; 120 players, GW2/3/4; September1 cutoff; eight retained copies | Owned engineering evidence, excluded from real accuracy |
| ACCEL002 native/controlled numerical snapshots | SYNTHETIC; player projections/decisions, one-/three-GW horizons | Owned numerical regressions, excluded from real accuracy |
| ACCEL003 cohort/current-mode proofs | SYNTHETIC; four players, two GWs, eight distinct player-GW targets | Existing Stage12 engineering scores only; real cohort zero |
| Historical public fits/golden replays | UNVERIFIED_CUSTODY; fitted sources/model/replay evidence | No authenticated pre-outcome target forecast; explicit reconstructed records remain separate |
| GW1 event-prior candidate | UNVERIFIED_CUSTODY; parameter candidate | No frozen player forecast or activation authority |
| Owner-reported additional real freezes | UNVERIFIED_CUSTODY; artifact not independently identified | Additional approved locator/custody evidence needed; unresolved, not disproved |
| Explicit reconstructed source/replay records | HISTORICAL_RECONSTRUCTED; two metadata records | Excluded from real prospective accuracy |

Origins, target GWs and forecast SHA values that have not been authenticated are
unavailable; metadata dates or operation hashes never substitute for them.
The catalogue retains every available source/provenance pointer and missing
dependency instead of inventing a forecast identity for these families.

P01 forecast origin is `2026-10-03T13:38:40.513349Z`; frozen at
`2026-10-03T13:40:19.466686Z`; information cutoff
`2026-10-03T13:35:50.079403Z`. A target FPL Gameweek was not supplied and is not
inferred from its match dates. It is not a player xPts cohort. Immutable pins:

- Forecast semantic SHA: `96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a`.
- Forecast byte SHA: `e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee` (38,208,223 bytes).
- Source lineage: `f22766ff90726056f497c23cd5c2992ac90090ac5ac7b30e26053b6e5a6eaa97`.
- Fixture registry: `de447eb368a807d4edf701a75c094a8b3f4925aa3e87cbff9b9f4fadd63eba18`.
- Model: `f44ff80d48f4c8e78c09ea27f4344c2f63858c92b0ce0a7f19f9267d6bc5e366`.
- Training dataset: `437b61bbbb18eeda2b931382c795333c6172d1473d5725224bee5f24a46ef549`.

## 3. Evaluation achieved

One distinct real frozen match forecast was authenticated in the authorized
search, covering ten fixtures and thirty product rows. Real scoreable cohorts:
zero. Actual real scores computed: zero. Authenticated real player cohorts: zero.
The last local canonical label snapshot, authenticated October14, contains zero
admitted final results and ten missing/not-final fixtures. Today's provider state
was not queried. Missing labels never become zero goals or zero player points.
No model-quality conclusion, tuning, promotion or activation follows.

Model Performance now distinguishes the real P01 MATCH population from synthetic,
reconstructed, unqualified and missing-label records. It uses the existing
evaluation/scoring architecture and leaves unavailable real accuracy null.
The owned Wyscout-native formation adapter adds strict temporal canonical joins,
START/BENCH support, matchday-squad denominators, coverage/missingness and UNKNOWN
minutes. Two fictional fixtures/eight roles exercise the schema; no real supplier
dataset was acquired and the active Grade-E/carry-forward prior is unchanged.

P01 canonical OpenFootball permission was not globally consumed by A02/A03.
However, the original exact `3815152e978dd55e1dc1f115055050d4ed6b1735`
execution binding calls a full validator that cold-rederives parameter draws;
the later explicit no-draw-generation instruction conflicts with that path.
Independent reviews authenticate the exact conflict. The later nongenerative
view cannot silently inherit original code authority. No request was made,
controller approved, fallback retried or P01 regenerated. A02/A03 stay consumed;
the display-name candidate stays inactive. A04 concerns the OpenLigaDB candidate
and does not resolve this canonical code-policy decision.

The narrow decision and conditional five-GET/no-retry canonical reassessment are
in [EVALUATION-READINESS.md](../../../tickets/DMF-PULSE-ACCEL-004/EVALUATION-READINESS.md).
They require exact reviewed nongenerative code binding, rights, original all-ten
unique identity/finality/D+2 gates and descriptive source-policy disclosure.
The plan is not executable permission. Future player evaluation additionally
needs every upstream retention/evaluation right and original pre-deadline custody.
The inherited expiring GW9 proposal is not a freeze or new provider evidence;
qualify an actual still-future official deadline before any future cohort.

## 4. Distinct live-dashboard statuses

| Status | Evidence and limit |
| --- | --- |
| ENGINEERING_READY | Source implementation and owned installed acceptance; final publication additionally requires the detached exact-SHA 20/20 CI receipt |
| CREDENTIALS_CONFIGURED | NOT_CHECKED for the owner's normal slots; isolated synthetic entry was deleted |
| ACCOUNT_ENTITLEMENT_VERIFIED | NOT_CHECKED; current nonsecret plan/quota evidence missing |
| PROJECT_RIGHTS_APPROVED | Exact pilot scope NOT_GRANTED; standing source profiles do not supply pilot enrollment |
| CONTROL_LEDGER_READY | Production NOT_CHECKED; fresh test PostgreSQL only |
| LIVE_PILOT_AUTHORIZED | FALSE; trusted production registry empty |
| LIVE_PILOT_EXECUTED | FALSE; zero football-provider requests in this programme |
| PRODUCTION_ACTIVE | FALSE; no activation |

The installed owned run verifies actual server/pairing, spawned process worker,
shared authorizer/ledger, single-flight/reload behavior, one-/three-GW models and
optimizer, Player Lab/My Team, cancellation, expiry and cleanup. Synthetic
execution is engineering evidence. Neither account entitlement nor a real
recommendation is inferred from it.

## 5. Exact outstanding owner decisions

- Qualify the existing Odds account's dated nonsecret plan, allowed markets,
  remaining credits/reset and applicable terms. Approve exact manager, routes,
  purpose, qualified deadline and validity window. The concrete draft proposes
  one manually initiated one-GW MARKET_PRIMARY refresh: one EPL sport-wide GET,
  UK h2h+totals, one request/two reserved credits, day/period caps one request/two
  credits and zero retries. These are proposed bounds, not an invented balance.
- Permit/configure canonical control metadata separately, with actual immutable
  ledger identity and recovery receipt. Review the completed trusted enrollment,
  rebuild an enrolled wheel and rebind its final package before any live operation.
  [PILOT-DRAFT-PACKAGE-BOUND.json](PILOT-DRAFT-PACKAGE-BOUND.json) is INCOMPLETE/NOT_GRANTED.
- Decide the narrow reviewed nongenerative P01 canonical code binding described
  above. This does not revive A02/A03, approve a source switch or tune from P01.
- Supply an additional approved local artifact/folder locator and original freeze
  custody if other real predictions lie beyond this bounded inventory. Qualify
  retention/evaluation rights for every upstream dependency before a real player
  cohort is stored or scored.
- Technical acceptance and any later production activation are separate decisions.
  No additional Odds account or secret disclosure is requested.

## 6. Publication and protected evidence

Branch: `readiness/DMF-PULSE-ACCEL-004-real-operation`; immutable parent:
`9b6d3f957e130e0832b39aee9940810eefa05535`. Checkpoint history remains append-only.
The original dirty Availability tree is preserved, including its 19 CP0-hashed
dirty file bodies. All eleven protected artifacts and 157 numerical source
identities remain unchanged. P01 is reauthenticated without a generative validator.

Full formatting/lint, both native-platform typing contexts, frozen provenance,
PostgreSQL control/rights/migrations, performance, six installed-wheel commands,
native credentials, actual browser and exact controlled one-/three-GW numerical
checks have dedicated source/package-bound receipts. Independent source review
records explicit 235→962 typing and 962→a250 cutoff disclosure bridges. The
earlier Linux typing failure, cutoff failure, native ordering diagnostic and local
timeout/interrupted attempts are preserved; none is counted as a pass.

The final external release receipt must authenticate the exact final Git commit,
canonical remote equality, first full attempt of all twenty unchanged CI jobs,
zero skipped tests, derived coverage arithmetic and downloaded artifacts. The
actual review ZIP must contain at most twenty files and at most5MiB both
compressed and uncompressed, with independently checked member hashes and no
private provider bodies or secrets. A previous source CI run, estimate or partial
job set cannot supply this gate. Human acceptance remains separate.

DMF_PULSE_ACCELERATION_WAVE_004_FINAL_HANDOFF
