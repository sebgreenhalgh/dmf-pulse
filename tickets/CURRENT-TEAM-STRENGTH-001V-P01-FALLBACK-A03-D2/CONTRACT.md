# A03-D2 offline metadata compatibility review

Immutable parent: `dde795c85f68d87578d3432576dac5d600794a32`.
Human execution contract is preserved verbatim in this ticket's evidence directory.
Authority precedence remains specs/manifests/authority_manifest.json, including
A3 data foundation, A8 events and B1 backtesting scopes; accepted ADR-DATA-004,
ADR-DATA-005, ADR-DATA-006, ADR-EVAL-001, ADR-EVAL-004, ADR-EVAL-006 and
ADR-ASSUR-006 govern rights, temporal labels, frozen evaluation and assurance.
This ticket creates no acquisition authority or new model/scoring decision.

## Scope

Only offline metadata diagnostics, tests, wheel verification, documentation and
new D2 evidence. Allowed runtime edits: ingestion/p01_fallback.py,
ingestion/p01_fallback_diagnostics.py and new ingestion/p01_match_metadata.py.
No provider requests, result acquisition, credential access, actual P01 scoring,
forecast reconstruction/refit/draw generation, activation, PR, merge or tag.
A02 and A03 remain permanently consumed. D2 changes invalidate the old A03
source-bound independent review; neither old authority nor synthetic success
permits execution with D2 code.

## Reconstruction at the immutable parent

`project_final_facts` has two explicit MATCHDAY_RESPONSE_INVALID exits:
the parsed top-level value is not a list; or the composite per-row metadata
predicate fails. A03's authenticated provider_match_rows=10 rules out the first.
Its zero finished/projected counters and metadata reason identify failure in
the first row's composite metadata gate, before matchIsFinished is evaluated.

The composite rejects any of:

| Field | Actual parent predicate | Purpose |
| --- | --- | --- |
| leagueId | equality to 5996 and exact Python int type | Governed returned competition identifier; refuse bool/float coercion |
| leagueShortcut | equality to pl | Governed route competition shortcut |
| leagueSeason | equality to 2026 and exact int type | Governed Match season, not League metadata string schema |
| leagueName | equality to Premier League | Legacy A02 compatibility restriction; not established as a canonical identity key |
| group.groupOrderID | equality to 6 and exact int type | Governed round/matchday |

Missing/wrong-shaped row or group, if reached, takes `_object`'s separate
PROVIDER_FIELD_TYPE_INVALID path at the parent. Earlier predicates short-circuit.
Group-order absence/wrong type/value can take the composite metadata exit.
Neither the exact failed predicate nor its actual value was retained. A03 does
not establish whether the provider has final results; zero finished rows counts
rows that passed metadata and finality, not the response's finished statuses.

## Offline provider evidence and policy

RETAINED-SCHEMA-EVIDENCE.json authenticates retained Swagger bytes and exact JSON
pointers. Source: https://api.openligadb.de/swagger/v1/swagger.json ; retained
byte SHA ca2eb416a4c68f234c1d0989302c0d9ee3ae5fffce175d02a05cdb599f44577b.
No retrieval during D2. Match defines integer leagueId/leagueSeason and Group
integer groupOrderID. Shortcut and leagueName are nullable strings; group is
nullable. Route inputs are shortcut, season and groupOrderId, not leagueName.
League's season is a nullable string; that separate schema does not justify
coercing Match season. This documentation has no enum/const requiring a fixed
leagueName, no uniqueness/immutability guarantee and no actual A03 response.

Inference: leagueName is descriptive/nonrouting. Narrow proposal: a separately
governed future revision could stop requiring exact display-name equality while
preserving all canonical checks, unique oriented frozen aliases and exact ten.
Status: **PROPOSED_UNAPPROVED**. Live compatibility and the exact A03 cause remain
unknown. The active name restriction and all existing admission rules remain.
No alternate names, nulls or malformed metadata are newly admitted by D2.
The retained source is used under the already qualified A01/A02 rights profile;
no expansion of raw-data storage, redistribution, training or access rights.

## Closed diagnostic contract

Five new reasons: METADATA_LEAGUE_ID_INVALID, METADATA_LEAGUE_SHORTCUT_INVALID,
METADATA_LEAGUE_SEASON_INVALID, METADATA_DISPLAY_NAME_INVALID,
METADATA_MATCHDAY_INVALID. All bind to PROJECT_FINAL_FACTS.
Optional SafeDiagnostics.metadata_failure contains only classification
METADATA_VALIDATION_FAILED, a closed field identifier (leagueId,
leagueShortcut, leagueSeason, leagueName, group or group.groupOrderID), and a
closed category MISSING, WRONG_TYPE or MISMATCH. Missing means absent key;
null is wrong type. Group missing/wrong object type is distinguished from its
nested order ID. Stable integer fields reject bool and equal-valued floats.
First failure follows original predicate order. No values, expected values,
row positions, teams, provider fixture IDs, scores, body or arbitrary text.

Additive v1 extension: absent metadata_failure is omitted from all serialization.
Historical diagnostic representations and semantic hashes are unchanged;
historical MATCHDAY_RESPONSE_INVALID remains readable and is not retrospectively
reclassified. New reasons require field/category and matching stage/reason.
Old readers cannot understand new extended records; no old reader is authorized
for new execution. Scoring/outcome artifacts and numerical kernels are unchanged.

## Before any A04

Resolve metadata compatibility with admissible retained provider-contract/live
schema evidence under separate authority, or keep uncertainty explicit; approve
any proposed policy revision through governance and independent review with
stable identity/exact-ten/ambiguity regressions. Bind reviewed implementation
and green CI to its exact SHA. A separate fresh human one-shot authority and
durable consumption controls are required. D2 provides none of these access
permissions; A03 cannot be retried and no result availability is inferred.
