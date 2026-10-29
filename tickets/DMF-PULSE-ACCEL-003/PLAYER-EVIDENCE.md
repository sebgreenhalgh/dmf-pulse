# CP4 fixture participation evidence

This implementation constructs useful descriptive starts/minutes evidence from an
authenticated, repository-owned synthetic fixture. It performs no real source
acquisition, persistence, training or production prediction. The accepted Stage-7
and Stage-9 mathematics, parameters and activation state are unchanged.

The public service is:

```python
from dmf_pulse.player_evidence.demo import owned_demo

report = owned_demo()
print(report.mode, report.status, report.semantic_sha256)
```

The companion Typer application exports `player_evidence_app` for registration as
`dmf player-evidence`. Its `demo` command runs the same service; `demo --revised`
selects a later owned cutoff. It supports no provider URL, credentials, arbitrary
input files, source overrides, rights bypass or production switch.

## Qualification and provenance

`build_features(body, source=..., request=...)` authenticates the source descriptor
and exact bytes before parsing or feature construction. Only the packaged
`owned-participation-v1.json` body, pinned to SHA-256
`6369d05ed2c4616d4029bd11e658749ea7180696b9032dd20f36dd2e4a097d0c`, is
qualified. The independently fixed digest also authenticates the installed resource
before use. A caller-supplied source name, licence, wrapper, hash or approval cannot
admit a different body. All real, proposed, revoked, training and production
purposes remain closed. This local owned-fixture qualification does not expand an
active provider rights profile or the PostgreSQL research ledger registry.

The complete source fixture has 13 fixtures across two seasons, 20 exact fixture
roster records, and 20 participation vintages including one append-only correction.
All identities and values are invented engineering examples, not observations of
real players. Its purpose and licence identity explicitly say owned synthetic.

The strict schema rejects unknown fields, boolean integer substitution, nonfinite
numbers, binary floating-point JSON, duplicate keys, excessive size/depth, naive
datetimes, impossible relation/clock combinations and broken revision chains.
UTC normalization occurs at the typed boundary. Raw JSON decoding grants no rights
and is not a feature-building or storage service.

## Exact temporal semantics

- Provider identifiers are scoped by entity kind and season, mapped to canonical
  UUIDs with effective intervals and their own observed/usable clocks. Player-name
  matching and current-team historical backfill are absent. More than one eligible
  mapping fails closed.
- Fixture UUIDs and source fixture IDs are unique and map exact season/home/away
  teams. Historical roster membership explicitly belongs to a particular fixture
  and source team. Observations disagreeing with that team fail closed.
- A verified fixture roster is required for any observation to enter descriptive
  features. Missing or unknown roster data do not imply OUT, DNP, injury or zero.
  START/BENCH/OUT are explicit source facts; positive minutes never imply START.
  Unused bench zero is valid. Unknown role and unknown minutes have separate reasons.
- Fixture completion, roster, observation and mapping must all be usable by the
  requested cutoff. Only FINAL fixtures contribute observations. The latest
  eligible participation revision is selected; later corrections cannot replace
  the earlier vintage at an earlier cutoff. Each revision binds its exact prior
  semantic hash and monotonically later usable time. Forks, missing predecessors
  and timestamp reversals are rejected.
- A future fixture or source/mapping vintage cannot become an earlier feature.
  A source player not mapped by the cutoff contributes only to the unattributed
  roster count; a future mapping is not used to attribute missingness to a player.
- The bounded fixture window selects the most recent known opportunities for the
  requested canonical player within the date window. Explicit OTHER_TEAM exclusions
  preserve transfer history; only the exact requested team supplies features.
  Provider matchweek numbers are not treated as FPL Gameweeks. Two nearby fixtures
  remain separate observations, including potential double-Gameweek fixtures.
- The sole accepted descriptive minute convention is explicit regulation 0..90.
  Stoppage-inclusive and unsupported conventions remain visible exclusions for
  minutes; their explicit role may still contribute role evidence. No clipping,
  FPL-minute equivalence, substitution-time reconstruction or extra-time conversion
  is invented. OUT cannot claim positive minutes under any convention.

## Features and limitations

Each player receives the requested identity, opportunity/selected counts, four
explicit role counts, empirical start rate, known-minute mean, empirical 60+
frequency, and unconditional/START/BENCH minute count distributions. Each mean and
rate carries an explicit numerator, denominator and nullable value. Known role and
known minute denominators differ deliberately. Empty history is unavailable, never
an invented zero or a silent position prior. Missingness reasons and observation
age are explicit. Source, mapping, roster and selected revision hashes form the
lineage receipt. The report validates its exact requested population and reconciles
the displayed counts and features.

Arithmetic is fixed `DECIMAL_40_HALF_EVEN` and independent of the caller's decimal
precision/rounding context. Output is deterministic, JSON-roundtrippable, and has a
semantic SHA. The empirical count distributions expose support and variability;
they are not calibrated predictive PMFs or estimated confidence intervals. Status
is always `SYNTHETIC`, `EVIDENCE_ONLY_NOT_MODEL_INPUT`, activation false, and
`NOT_ESTIMATED_EMPIRICAL_SUPPORT_ONLY`.

The early owned player-1 oracle has two START, one BENCH, one OUT and one unknown
role after excluding two earlier-club fixtures. Start frequency is 2/4; mean known
minutes is 85/4 = 21.25; 60+ frequency is 1/4. The unknown role with 25 minutes is
not a start. The later source correction changes one START from 60 to 59, which
changes the 60+ count, while incomplete fixture/unknown roster/unsupported minute
conventions remain excluded explicitly. These are analytical engineering oracles,
not evidence of real forecasting accuracy.

The read-only feature report is the future integration seam. A later, separately
accepted adapter could bind qualified fixture evidence to the existing
`availability.models.HistoryRow` and Stage-7 provenance contracts. It would also
need manager-regime/position/sequence mappings, approved training purpose, minute
compatibility and chronological validation. This implementation performs none of
that conversion and cannot substitute a challenger into accepted projections.

## Historical/current source assessment

Primary public documentation was researched on 2026-10-29 UTC. No provider JSON,
accounts, credentials, data files, subscriptions or supplier contacts were used.
Documentation proves a candidate's description, not actual file completeness or a
DMF acquisition/training approval.

| Candidate | Coverage and useful fields | Rights and remaining decision |
|---|---|---|
| Pappalardo/Massucco Wyscout research release | Authors describe full 2017/18 English first division alongside four other domestic leagues and two tournaments. Match documentation describes lineup, bench, substitutions/minute, source IDs and `hasFormation`. No current-season feed promised. | Matches item 7770422 and Players item 7765196 explicitly declare CC BY 4.0. Attribute authors/source, cite the paper, link the licence and identify transformations. Pin required item versions/bytes and assess privacy/other-rights caveats before qualification. Best historical open candidate; not acquired. |
| Hudl StatsBomb open data | Official 2023 release describes a full EPL 2015/16 season (competition 2 / season 27). Original Invincibles release is 32 Arsenal fixtures from 2003/04, not full EPL coverage. Events/lineups documented. | README attribution/logo requirements are additional to the separate user agreement. Official Invincibles article describes noncommercial fan/academic use and separate commercial discussion. Full LICENSE.pdf was not parsed by the browser, so full licensing remains unverified and qualification closed. |
| API-Football | EPL listed; lineup/bench, fixture events and per-player statistics documented. Exact historical season/fixture/field completeness varies and was not observed. | Terms contemplate apps/fantasy projects but disclaim granting competition/publication licences; required third-party permission remains the user's obligation. Subscription alone does not establish retained research/training rights. No account/plan inspected. |
| Sportmonks | Paid EPL coverage; documented starter/substitute types, lineups/details and minute statistics. Historical squads advertised from 2005 with explicit incomplete competition coverage. Exact EPL field/season coverage remains unverified. | Terms permit product data storage/transfer/distribution and restrict resale. Integrity page expressly disclaims official competition rights. Exact plan/field scope, retained research/training and post-termination terms require resolution. Product/FAQ xG and trial statements differ; no favorable inference or purchase. |

Primary references:

- [Original author paper](https://www.nature.com/articles/s41597-019-0247-7),
  [author repository copy](https://iris.cnr.it/bitstream/20.500.14243/362201/1/prod_412387-doc_145167.pdf),
  [collection](https://figshare.com/collections/Soccer_match_event_dataset/4415000/2),
  [Matches item](https://figshare.com/articles/dataset/Matches/7770422),
  [Players item](https://figshare.com/articles/dataset/Players/7765196),
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- [StatsBomb README](https://github.com/hudl/open-data),
  [EPL 2015/16 release](https://blogarchive.statsbomb.com/news/the-2015-16-big-5-leagues-free-data-release-premier-league/),
  [Invincibles release and licence caveat](https://www.hudl.com/blog/invincibles-project-classics-data-pack-1),
  [separate licence file](https://github.com/hudl/open-data/blob/master/LICENSE.pdf).
- [API-Football terms](https://www.api-football.com/terms),
  [coverage](https://www.api-football.com/coverage),
  [v3 documentation](https://www.api-football.com/documentation_v3).
- [Sportmonks terms](https://www.sportmonks.com/terms-of-service/),
  [integrity/provenance](https://www.sportmonks.com/integrity-support/),
  [FAQ](https://www.sportmonks.com/faq/),
  [v3 lineups](https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/includes/lineups),
  [historical squad coverage caveat](https://www.sportmonks.com/glossary/squads/).

No source on this shortlist is activated. OpenFootball final team scores do not
supply player participation. A mirror's code licence does not establish rights to
its FPL data. Supplier assists, minutes, xG and defensive events are not silently
equated with official FPL scoring labels. Current calibration weaknesses remain
the historical Grade-E allocation prior, early-season/sparse minutes, roster and
role changes, missing substitutions, and unqualified real retained labels.
