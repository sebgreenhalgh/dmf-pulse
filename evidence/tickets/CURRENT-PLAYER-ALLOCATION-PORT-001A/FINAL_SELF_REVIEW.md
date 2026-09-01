# CURRENT-PLAYER-ALLOCATION-PORT-001A engineering self-review

## Adversarial review

- Provenance: the central artifact still says `CANDIDATE_NOT_ACCEPTED`; historical acceptance is a
  separate `HUMAN_ACCEPTED_PRIVATE_GW1_ONLY` record. Output explicitly adds
  `DONOR_PRIVATE_ACCEPTANCE_IS_NOT_PORT_ACCEPTANCE` and `NOT_PRODUCTION_ACTIVE`.
- Identity: current official-FPL numeric IDs and identity hashes are exact. Canonical Stage-7 UUIDs
  are explicit caller mappings. Donor UUID5 values only validate immutable lineage. There is no
  player-name lookup, fuzzy substitution, or stale-team tolerance.
- Missingness: absent profiles, teams, role shares, shooter evidence, and candidate sets block.
  The only goal-share shooter proxy is visibly restricted to `TEST_SYNTHETIC`; governed donor
  requests cannot use it.
- Conservation: Stage-8 score cells are sampled by the current service. Each output scenario
  independently reconciles goal-event count/team split, scorer versus own-goal mechanism, scored
  penalty links, and player aggregate vectors.
- Minutes: generated vectors carry exact Stage-7 half-open intervals. The event model revalidates
  goal, assist, own-goal, penalty, goalkeeper, and shot actors at each event minute.
- Saves/penalties: only on-pitch GKs receive saves; each save has an on-pitch opposition shooter;
  saved penalties share one explicit penalty/save link; scored penalties count once only.
- Stage 9: no expected-points model or independent bonus estimate was introduced. The canonical
  rules adapter calculates integer components/BPS/bonus from each coherent scenario. Marginals are
  recomputed from, and exactly agree with, the retained joint matrix.
- Reproducibility: candidate ordering is canonical, randomness uses the existing namespaced seeded
  generator, artifact/request/source hashes are explicit, and fixed input/seed reruns are equal.
- Port contamination: current Stage7/Stage8/Stage9 and current-FPL contracts remain authoritative.
  No obsolete donor bridge, acquisition, score prior, scorer, workflow, or optimiser was copied.
- Side effects/security: import performs no network, database, subprocess, environment mutation,
  or filesystem write. Resources are wheel-contained. No credential or real private input exists.
- Isolation: the pre-existing dirty CURRENT-AVAILABILITY-001A tracked and cached Git object IDs
  remained unchanged from startup.

## Finding and disposition

One material P2 was found during broad collection: eagerly importing the current-FPL contract
from the new public prior module formed a CLI import cycle through manager state. The dependency is
now type-only under `TYPE_CHECKING`; strict mypy and the formerly failing top-level CLI collection
path pass. No assertion or API was weakened.

- P0 found / unresolved: 0 / 0.
- P1 found / unresolved: 0 / 0.
- Material P2 found / unresolved: 1 / 0.

This is an engineering self-review, not independent review or human acceptance.

`CURRENT_PLAYER_ALLOCATION_PORT_001A_SELF_REVIEW_CLEAR_PENDING_INDEPENDENT_REVIEW`
