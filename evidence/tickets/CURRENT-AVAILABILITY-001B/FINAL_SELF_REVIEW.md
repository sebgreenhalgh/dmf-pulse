# CURRENT-AVAILABILITY-001B engineering self-review

## Adversarial findings

- Provenance: the manual family cannot masquerade as empirical Bayes; every manual player is
  grade D with an explicit manual reason, while empirical teams reject that reason.
- Evidence: operator scenarios remain manual soft evidence. Degenerate p_start=1 or p_out=1 is
  refused without an aligned allowed hard override. Hard scope, time, roster, and role alignment
  are revalidated.
- Time: UTC is mandatory; usable time cannot precede source/entry time; evidence must be usable
  and unexpired at as_of; `as_of > information_cutoff` fails; Stage 8 retains its post-cutoff gate.
- Exactness: JSON floats, duplicate keys, non-finite constants, non-integer counts, arbitrary
  normalization, and hidden RNG are absent or rejected. Counts expand exactly to 256.
- Coherence: the accepted Stage-7 lineup contract revalidates all 256 lineups; the manual hash also
  binds official minutes and source scenario identity.
- Hashing: dataset, policy, provenance, scenario, player, team, bundle, context, manifest, and file
  identities are deterministic and semantic. The compatibility artifact is explicitly a policy
  hash, never described as a learned model.
- Compatibility: model families remain a closed union; arbitrary strings fail; empirical artifacts
  and frozen MIN-007G schemas are unchanged; affected public Stage-8 schemas match runtime output.
- Private output: resolved paths must retain the exact private marker and cannot traverse symlinks.
  All target conflicts are checked before the first write; identical reruns preserve identical
  bytes; no real manual judgement fixture is committed.
- Side effects: imports perform no network, database, provider, subprocess, environment, or
  filesystem-write operation. The capability writes only when its explicit CLI is invoked.
- Isolation: the dirty 001A tracked and cached diff identities match before and after.

## Findings disposition

- P0 found / unresolved: 0 / 0.
- P1 found / unresolved: 0 / 0.
- Material P2 found / unresolved: 2 / 0.

The two material P2 findings were a normalized-path marker escape and pre-conflict partial output.
Both were fixed and have direct tests. This is an engineering self-review, not independent review
or human acceptance.

`CURRENT_AVAILABILITY_001B_SELF_REVIEW_CLEAR_PENDING_INDEPENDENT_REVIEW`
