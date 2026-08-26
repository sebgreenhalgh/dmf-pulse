# CURRENT-FPL-STATE-001B donor reconciliation

The historical donor was inspected, not merged, rebased, or cherry-picked.

## Immutable donor identity

- Branch: `readiness/GW1-2026-27-live-input-initial-squad`.
- Commit: `d4cc759d4600489c21ba738cfc9b357cc380554e`.
- `src/dmf_pulse/ingestion/odds/identity.py` blob:
  `4f9a515a3dd3024523f3e9393eb1de452a07fbc8`.
- `src/dmf_pulse/ingestion/odds/mapping.py` blob:
  `a9a176274f715fe25da83ce1d1cd794c3a38b4e3`.
- `tests/unit/ingestion/test_fpl_odds_team_identity.py` blob:
  `fb5125df5660e16092309813c0d34d51212a701c`.
- `tests/unit/ingestion/test_fpl_odds_fixture_identity.py` blob:
  `1f399f300402c002974204b59b3caa5b4074b41b`.

## Ported semantics

- Explicit provider-team text to official-FPL team mappings with no fuzzy fallback.
- Explicit provider-event to official-FPL fixture bindings.
- Competition, season, provider, approval, and usage-scope binding.
- Deterministic mapping-plan, consumed-input identity-view, Odds event-identity, and provider
  provenance digests.
- Exact home/away orientation, exact UTC kickoff equality, complete one-to-one target fixture
  coverage, ambiguity rejection, and tamper self-validation.
- Private transient output with distinct semantic and source-lineage hashes.

## Generalized semantics

- All `gw1-fpl-odds-*` labels became `current-fpl-odds-*`; tests use target Gameweek 2.
- The accepted 001A `semantic_sha256` is bound directly. A separate digest covers the complete
  identity view actually consumed by 001B instead of rebuilding an obsolete subset of 001A.
- A common cutoff may precede the official deadline; it is no longer forced to equal the deadline.
- Explicit target bindings may be a subset of all LIVE-ODDS events. Unrelated later events are
  classified outside-target unless they form an exact duplicate target candidate.
- Fixture approvals must be fresh for the exact current source captures and precede both mapping
  decision and cutoff.
- The accepted LIVE-ODDS provider-native identity, market semantics, rights, temporal state, and
  provenance contracts remain unchanged and are consumed by the separate bridge.

## Superseded behavior

- The donor's partial reconstruction of the pre-001A FPL semantic digest.
- The donor equality assumption between information cutoff and target deadline.
- The donor whole-provider-response count equality with target-Gameweek fixture count.
- Donor assumptions tied to Gameweek 1 and obsolete Odds interfaces.
- Any current-state mapping loader or durable current mapping artifact.

## Deliberately omitted behavior

- Readiness-branch composition/orchestration, initial-squad behavior, and downstream modelling.
- Network acquisition, real current aliases/event identifiers, operator credentials, persistence,
  database use, cache, backup, public mapping CLI, or disclosure-bearing summary.
- Manager state, availability/minutes, projections, consensus, optimization, and activation.

No current mapping persistence was added. Repository tests and evidence contain synthetic names,
identifiers, fixtures, and prices only.
