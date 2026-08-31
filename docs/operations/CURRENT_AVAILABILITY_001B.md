# CURRENT-AVAILABILITY-001B private manual transient minutes bridge

CURRENT-AVAILABILITY-001B is **PRIVATE**, **TRANSIENT**, **MANUAL**,
**NOT_MODEL_DERIVED**, **GRADE D**, and **NOT_PRODUCTION_ACTIVE**.

It exists because the accepted current Stage-7 path cannot yet run a real current/historical
minutes model: the repository has no accepted real historical minutes evidence for that path.
This adapter lets a private operator supply the uncertainty distribution directly without
relabeling manual judgement as historical observations and without bypassing the Stage-8
provenance gate.

## Operator command

```text
dmf availability manual-override \
  --input fixture_manual_minutes.json \
  --output-dir artifacts/dmf-private-transient
```

The output path must be at or below a directory named `dmf-private-transient`. That directory name
is repository-ignored. Do not place real operator input or generated output elsewhere in the
repository, and never add it to Git.

The command writes five deterministic immutable files:

- `manual-input.canonical.json` — the complete canonical validated private input;
- `home-team-minutes-projection.json` — the home `TeamMinutesProjection`;
- `away-team-minutes-projection.json` — the away `TeamMinutesProjection`;
- `stage7-minutes-context.json` — the accepted Stage-8 identity boundary;
- `manual-override-manifest.json` — provenance, policy, identities, and file hashes.

An identical rerun reuses identical bytes. A different artifact at an existing output name is a
hard conflict; the command does not overwrite it.

## Input contract

The root schema version is `private-manual-transient-minutes-v1`. It declares one canonical
fixture UUID, distinct canonical home/away team UUIDs, one UTC `as_of`, an
`information_cutoff`, explicit private provenance, and one scenario set per team.

Each team explicitly declares:

- `bench_size = 9` and `bench_goalkeeper_slots = 1`, matching the accepted 256-scenario Stage-7
  compatibility policy;
- one to 256 canonically ordered weighted scenarios;
- positive integer scenario `count` values summing exactly to 256;
- the identical canonically ordered 20–40-player roster in every scenario;
- for every player, canonical `player_id`, `position`, `role`, and integer
  `official_minutes` in 0..90;
- any authoritative hard role overrides, canonically ordered by player UUID.

No probability is accepted as input. JSON floats, duplicate keys, non-finite numbers, arbitrary
normalisation, missing roster members, and silent repairs are rejected.

Every scenario must contain exactly 11 `START` players, exactly one starting goalkeeper, exactly
nine `BENCH` players including one goalkeeper, and a coherent `OUT` remainder. `START` requires
positive minutes, `OUT` requires zero minutes, and `BENCH` may have zero or positive minutes.

## Manual evidence governance

The fixture mixture is soft analyst evidence. Its provenance explicitly records a generic
operator reference, evidence/source type, source/entry/usable timestamps, reason, expiry, fixture
scope, private/transient classification, and the false `model_derived` and
`production_suitable` claims. All evidence must be usable and unexpired at `as_of`, and
`as_of <= information_cutoff`.

Soft evidence may not produce `p_start = 1` or `p_out = 1`. A deterministic role requires one
aligned fixture/team/player-scoped hard override. Supported hard classes are official suspension,
formal ineligibility, and an official lineup explicitly classified for a non-FPL-cutoff use case.
Suspension and formal ineligibility can assert only `OUT`. Ordinary analyst judgement, manager
quotes, training reports, or status observations remain soft.

## Exact projection semantics

Scenario counts expand in canonical order to exactly 256 lineups with no RNG. Existing Stage-7
lineup validation independently rechecks the complete expanded roster, START/BENCH/OUT roles,
XI, goalkeeper, bench, marginal, and hash coherence. The manual scenario-set hash additionally
binds every official-minute value.

For each player, role probabilities and the 91-bin minute PMF are exact empirical frequencies of
the expanded scenarios. `p_zero_minutes`, `p_appearance`, `p_60_plus`, and `expected_minutes` are
derived from that PMF using the existing exact-Decimal public formatting. There is no smoothing,
regression, shrinkage, interpolation, league-average fill, hidden fallback, or manufactured
uncertainty.

Every player is grade `D` and includes `MANUAL_TRANSIENT_OVERRIDE`. The team model family is the
closed identifier:

```text
PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1
```

It can never be emitted as `REGULARISED_EMPIRICAL_BAYES_COHERENCE_V1`.

For this family, `dataset_sha256` hashes the complete canonical manual input body.
`model_artifact_sha256` hashes the versioned deterministic transformation policy embedded in the
manifest; it does **not** identify a learned statistical model. Existing empirical-Bayes output
fields, bytes, hashes, and validation semantics are unchanged.

## Upgrade path and limitations

Replace this adapter with the normal model-derived Stage-7 projection once accepted current-player
history/model evidence is available. Stage 8 already consumes either truthful family through the
same `Stage7MinutesContext`; no downstream consumer needs to pretend that manual output was
model-derived.

This bridge does not acquire evidence, authenticate a provider, verify a real fixture against a
live catalogue, persist to a database, calibrate a model, produce Stage-9 player events/points,
optimise an FPL team, or activate production. Canonical identities and manual assertions must be
prepared and reviewed outside this command. It is temporary private decision support, not a
production-ready availability model.
