# Offline formation evidence adapter

The Wyscout Matches research release is the highest-value next historical
candidate from the retained source assessment. This slice implements an actual
native-formation transformation and temporal feature path using newly authored
fictional fixtures. It has no network/data acquisition, real-source enrollment,
training, production prediction, availability parameter change or activation.

## Rights, coverage and provenance

The primary [Matches item](https://figshare.com/articles/dataset/Matches/7770422)
identifies Luca Pappalardo and Emanuele Massucco, publication
2019-02-26T12:15 and CC BY 4.0. Its documentation describes explicit lineup,
bench, substitution and formation-availability fields. Those fields support a
direct role transformation; clock minutes do not establish FPL played minutes.

The [author paper](https://www.nature.com/articles/s41597-019-0247-7), published
2019-10-28, describes English first division 2017/18, alongside four other
domestic leagues and two international tournaments. Table 1 reports 380 English
matches; Box 3 describes the nested formation subdocument. This is an author
coverage claim, not an observation that every fixture/player/formation/file is
complete. No current-season coverage is established. Direct article/PDF fetches
hit the publisher identity redirect; primary-domain indexed article/PDF text
provided the schema/table evidence. University-repository PDF access returned
403. No dataset file, archive or provider account was accessed.

The [CC BY 4.0 deed](https://creativecommons.org/licenses/by/4.0/) describes reuse
and transformation with attribution, licence linking, change disclosure and no
additional restrictions. It also identifies other-rights and warranty limits.
Any later real qualification must pin exact item versions/bytes and licence
evidence, retain authors/title/DOI/licence/transformations, and resolve project
purpose, privacy and other applicable rights. These public documents do not
enroll a real source. Reviewed 2026-10-30; bounded URL/retrieval/failed-fetch
receipts are retained separately in ignored review output.

## Implemented source contract

`adapt_owned_wyscout(body, source=...)` requires the exact new repository-owned
native source descriptor and payload SHA before parser or binding-resource
access. It then authenticates the fixed owned temporal binding bytes. Real,
reconstructed, live-observed, proposed, revoked, training and modified-source
descriptors are rejected. Only the exact additional synthetic derived payload
is admitted by the existing descriptive feature qualifier, which rechecks the
native, binding and derived bytes. The original owned fixture and real-source
closed default remain intact.

The native fixture wraps two fictional match documents in an unmistakable
OWNED_SYNTHETIC envelope. The required documentary core is match/competition/
season ID, dateutc, Played/Regular status, home/away team keys/IDs, hasFormation,
and nested formation.lineup/bench/substitutions. All consumed identity, role and
status fields are strict. Unused native labels, scores, card statistics and
gameweek are unretained; provider gameweek is never assigned to FPL gameweek.
The strict JSON decoder bounds bytes/depth and rejects duplicate keys, floats,
nonfinite numbers, boolean IDs and shape/identity disagreements. This is
documented-subset acceptance against owned examples, not a claim of verified
compatibility with every real release file or payload variant.

Every native fixture maps exactly once to a supplied canonical fixture, season,
competition, kickoff and home/away binding. Consumed players and both fixture
teams require unique temporal canonical maps. Provider aliases cannot collapse
two participating players or opposing teams onto one canonical identity. The
binding supplies independently qualified finality/completion bounds; completion
is not inferred by adding ninety minutes. Missing/ambiguous mappings, wrong
seasons/teams/sides, duplicate fixtures/roles, impossible substitution identity
or reversed substitution clocks fail closed.

Lineup gives START; bench gives BENCH. A substitute entering at minute 60 stays
BENCH. A bench player with no substitution record has unknown minutes, not zero.
An owned starter with a card statistic has unknown minutes, not ninety. All
native minute outputs are `None`, NOT_SUPPORTED and UNSUPPORTED convention.
Starts are never inferred from minutes. A missing formation supplies no role or
roster fact; a mapped player absent from all matchday squads does not become OUT.

The wrapper explicitly reports native fixture count, missing-formation
team-fixture count, observed matchday membership count, and the conditional
matchday-squad denominator. The existing feature builder produces counted
descriptive start rates, unknown minute means/60-plus rates with zero known-minute
denominators, per-player missingness and selected identity/vintage hashes.
These rates are not unconditional club-roster start probabilities or calibrated
predictive uncertainty. Missing formations exclude unproven club opportunities;
their count remains explicit rather than becoming negative labels.

## Temporal use, revisions and acceptance

`dmf player-evidence wyscout-demo` follows native byte authentication -> exact
canonical/temporal adaptation -> fixed derived-byte authentication -> existing
cutoff feature builder. `--before-release` selects no history, even though the
fictional fixtures finished earlier. The owned source simulates a retrospective
2019 vintage for 2018 matches; no actual retrieval is backdated. A later real
capture must use its actual retrieval/observation and correction-vintage clocks,
with usable time no earlier than every retained dependency's availability.

This source is a snapshot, so admitted observations begin at revision zero.
Neither changed bytes nor a caller-resealed descriptor can overwrite the pinned
snapshot. A separately qualified correction must retain its predecessor and
explicit append-only revision lineage under the existing participation contract.
No adapter turns a changed current snapshot into a pre-outcome historical freeze.

Tests include source/dependency tampering, exact fixture population, ambiguous
canonical aliases, temporal boundaries, direct role semantics, absent formations,
unknown players/minutes, before-release cutoff, immutable original source
regressions and complete CLI output. Tests use owned bytes only and prohibit
writes/model entry points on the descriptive path.

For a future qualified holdout, retain the existing chronological Grade-E/role/
candidate comparison plan. First audit real fixture/formation/identity coverage
and truly available vintage clocks. Freeze player/team/fixture/GW populations,
feature definitions, missingness cohorts, metric denominators, correction rules,
and prospective/retrospective classification before outcomes. Train/tune only
earlier development windows; compare unchanged Grade-E, role baseline and the
declared candidate on later untouched seasons/windows with paired support and
clustered uncertainty. The 2019 release cannot supply genuinely available 2018
features. This slice ran no real holdout and claims no empirical gain.

All 157 accepted numerical kernels, Grade-E/carry-forward settings, production
models, active source rights, P01 artifacts, A02/A03 consumption and A04/source
switch gates remain outside this change.
