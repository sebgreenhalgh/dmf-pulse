# P01 D3 policy and future execution readiness

The retained Swagger ca2eb416a4c68f234c1d0989302c0d9ee3ae5fffce175d02a05cdb599f44577b
(44,677 bytes) documents Match leagueSeason as integer and leagueName as nullable
string, without a required-field list. League's separate season representation is
not the Match contract. Route parameters are shortcut/string, season/integer and
groupOrderId/integer. No new provider documentation or results were retrieved.

| Field | Identity role | Legacy / candidate |
|---|---|---|
| leagueId | stable provider competition | strict integer5996 / unchanged |
| leagueShortcut | route competition | exact string pl / unchanged |
| leagueSeason | Match season | strict integer2026 / unchanged |
| group.groupOrderID | round identity | strict integer6 / unchanged |
| leagueName | descriptive label | exact Premier League / separate candidate below |
| oriented club aliases | frozen canonical fixture | unique exact-ten mapping / unchanged |
| finality/result kind/ID | regulation final outcome | finished true and unique90-minute result / unchanged |

Candidate v1 accepts exact or alternative nonblank strings, absent and null names.
It rejects wrong types, blank strings, length>256 and Unicode category-C text
(controls, surrogates and format characters). The latter are conservative local
candidate choices, not alleged provider guarantees. No fuzzy alias matching.

State: PROPOSED_UNAPPROVED / INACTIVE / SYNTHETIC_ONLY. The candidate refuses both
actual context and forecast hashes. It is not callable by an acquisition route.
Legacy strict metadata code remains byte-identical. Candidate projection alone is
not outcome admission: exact-ten and chronology still run through accepted admission.

ProjectedFinalFact.league_name is historically a canonical default. Candidate v1
therefore nests canonical_fact separately from provider_display_name state/value,
marks the label FROZEN_CONTEXT_NOT_PROVIDER_OBSERVATION, binds original body SHA,
and discloses transient canonical substitution used to reuse the strict projector.
Historical artifacts remain unchanged; their field is not retroactively recast as
observed provider text. Future real compatibility needs a separately approved schema
and provenance path; this synthetic candidate cannot authorize that change.

The only legacy admission modification rejects linked regulation IDs with bool,
float, string, null or missing types before comparison. Previously True/1.0 equaled1.
It tightens identity validation and leaves valid integer semantics and metrics fixed.

## Offline chain and stop points

| Stage | Exercise / remaining stop |
|---|---|
| Rights | Existing pinned profile authenticated; no expanded permission |
| Transport | Fake/byte-injected only; actual outage, non200, oversized body, bad JSON remain stop conditions |
| Schema | Strict metadata plus inactive candidate matrix; actual A03 field/value still unknown |
| Identity | Exact competition/season/round, oriented aliases, unique IDs/ten fixtures |
| Finality | Strict true, unique linked After90Minutes, no exceptional result |
| Time | Freeze<played<=retrieval; chronology and actual-date D+2 |
| Forecast | Reconstructed hash-distinct synthetic view; actual operational entry remains pinned P01 only |
| Scoring/report | Existing pure scorer and scorecard,10fixtures×3products; intermediates transient |
| Sealing | Only distinct synthetic receipt leaves new function; deterministic semantic hash and strict roundtrip |
| Persistence | CLI writes no files; controller may retain synthetic receipt; inherited immutable store tests cover collisions/paths |
| Promotion | No synthetic receipt is prospective evidence; no promotion/tuning/activation |

The public command `dmf events team-strength p01-fallback synthetic-readiness`
takes explicit local synthetic context/forecast and three source-shaped JSON files,
plus synthetic UTC as-of; optional --candidate exercises only inactive policy.
It returns gate/count/hash evidence with no labels or numerical scores. Actual context,
actual forecast, LIVE_OBSERVED mode and operational persistence of its receipt fail.
Accepted scorer intermediates remain the existing types internally; they are never
persisted or presented as actual P01 results by the new capability.

## Non-executable future A04 decision checklist

This prose is not an application authority instance, ticket, command or marker.
It grants zero provider requests. A02 and A03 remain permanently consumed.

1. Owner reviews the exact final implementation SHA, independent review and successful
   CI binding in the release handoff. A later code change requires fresh binding.
2. Resolve source contract assumptions: actual metadata values and current result
   availability remain unknown. Offline success cannot assert provider conformance.
3. Separately accept or reject a versioned real metadata policy and observed/canonical
   provenance schema. Candidate implementation is not policy acceptance.
4. Confirm narrow existing rights/source/fixture/finality/D+2/scoring constraints.
5. Provide fresh explicit one-shot A04 human authority bound to the reviewed SHA,
   separate consumed-marker identity, exact route/source/cohort and fail-closed rules.
6. Independently review any executable authority implementation before any request.

No A04 command/schema/active instance/marker is created here. No actual P01 score,
reconciliation request, tuning, model promotion or activation is performed.
Historical A03 conclusion remains first-row metadata gate before finality; exact
field/value unknown. It does not establish absence of final results.
