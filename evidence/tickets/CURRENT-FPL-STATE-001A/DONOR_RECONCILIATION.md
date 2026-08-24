# CURRENT-FPL-STATE-001A donor reconciliation

Authoritative parent: `2bc2783adc37d0956962d7574f73cbb6af711e28`

Historical donor ref: `readiness/GW1-2026-27-live-input-initial-squad`

Primary donor path: `src/dmf_pulse/ingestion/fpl/current.py`

Primary donor blob: `59bb878ef30158c02a8b9e9ab700e4b57fc003fc`

The donor was inspected as a reference. It was not merged, rebased, or bulk cherry-picked.

## Ported semantically

- operator-supplied bootstrap and fixtures files;
- bounded regular-file reads, distinct resolved paths, and symlink rejection;
- reuse of the accepted `parse_fpl_payload` bootstrap/fixtures contracts;
- immutable in-memory teams, players, positions, events, fixtures, provenance, rights, and quality;
- season-scoped official-FPL identities and provider-native price/status/news fields;
- target-event, cross-resource, cutoff, rights, and schema-drift gates;
- safe-summary-only CLI disclosure; and
- explicit no-network, no-database, no-storage, and operator-deletion outcomes.

## Rewritten for current main

- Current-main `FrozenModel`, parser, provider config, canonical hash, and rights models are used
  directly; no donor foundation file replaced later-main code.
- The rights gate now pins the complete approved profile shape, including approval status,
  version, retention zero, termination deletion, all denied capabilities, and fail-closed derived
  storage.
- Provider identity namespaces are validated against entity types, contracts validate their own
  lineage, and provenance binds both source and current-contract versions plus provider and rights
  configuration hashes.
- Game settings are retained as canonical JSON with an independently validated semantic digest,
  avoiding a mutable free-form dictionary in the private bundle.
- Receipt and usable times are observed separately and ordered explicitly.

## Generalised from the GW1 donor

- There is no default target Gameweek and no `gameweek == 1` semantic gate.
- Any positive operator-declared Gameweek may compile only when exactly present, unfinished,
  marked current or next by the supplied bootstrap, and backed by valid post-deadline fixtures.
- Tests cover Gameweek 2 as both next and current; no wall-clock inference or maximum-event
  fallback exists.
- GW1-specific downstream checkpoint text was removed from the summary and runbook.

## Deliberately omitted

- live or automated FPL transport, authentication, credentials, cookies, and schedules;
- database, object-store, cache, backup, artifact, raw, or derived current-state persistence;
- manager-owned squad/bank/transfer/chip state;
- FPL-to-Odds identity, aliases, kickoff binding, or event reconciliation;
- availability/minutes, markets, football-event priors, points, projections, optimisation, and
  orchestration; and
- PR, merge, tag, human acceptance, or production activation actions.

## Superseded donor details

The donor's GW1 default, GW1-only operational framing, mutable game-settings mapping, single
receipt/usable timestamp, and stale next-checkpoint status are superseded by the generalized,
self-validating current-main contracts in this ticket.
