# GW1-PLY-001 source and retention governance

No official FPL history was requested for this branch. All test payloads are
synthetic schema-equivalent values only.

## Future source boundary

- Template: `https://fantasy.premierleague.com/api/element-summary/{current_element_id}/`
- Allowed node: `history_past`
- Capture universe: the already mapped current FPL catalogue only; canonical
  internal UUID plus provider/season-scoped FPL player ID must agree.
- Allowed retained interpretations: completed-season `minutes`, `goals_scored`,
  `assists`, `yellow_cards`, `red_cards`, and, for goalkeepers, `saves`.
- Explicitly excluded from ability fitting: `total_points`, bonus, BPS,
  ICT/influence/creativity/threat, and start/end costs.

## Required future rights profile

```text
scope              PRIVATE_2026_27_GW1_ONLY
access             HUMAN_INITIATED_BOUNDED_UNAUTHENTICATED_TRANSIENT
raw_retention      FORBIDDEN
derived_retention  POSTERIOR_ONLY
redistribution     NONE
repeat_collection  REQUIRES_NEW_APPROVAL
```

The code ships no approval artifact. A self-consistent hash is not treated as
human approval merely because it can be syntactically parsed; an operator must
supply the separately recorded human decision and its expected SHA-256.

## Transience assurance

The capture boundary uses one injected serial GET transport. It has no
filesystem path, cache, log, artifact or raw-response return field. A response
body exists only while JSON is decoded into the allowed in-memory
interpretation, then is discarded. The public capture result exposes derived
evidence, schema fingerprint, optional permitted source hashes, successful
receipt timestamps, and a deletion manifest—never a body or literal response
row.

No durable API accepts real history rows. The only durable model is
`PlayerPosteriorArtifact`; it records rates, exposure, provenance, rights and
timestamps, but not source rows. Byte-for-byte source replay is deliberately
unavailable: `RAW_HISTORY_NOT_RETAINED_BYTE_REPLAY_UNAVAILABLE`.

The deletion manifest is designed to record a run ID, temporary object IDs,
deletion time/outcome, optional posterior artifact hash, and
`raw_history_persisted = false`. The command writes no raw temporary file.

## Future live execution guards

The implementation validates before transport construction, runs one request
at a time with at least one-second pacing, and stops without retry on HTTP 401,
403, 429, another non-200 result, authentication requirement, terms drift or
material `history_past` schema drift. It uses no credentials, sessions,
cookies, browser automation, historical catalogue discovery, or request storm.

A successful receipt is timestamped by the supplied clock immediately after
the response. Any receipt after the decision information cutoff fails. The
posterior compiler preserves the actual per-player successful-receipt time;
for a historical reconstruction such retrieval is explicitly not
`LIVE_OBSERVED` and may never be backdated.
