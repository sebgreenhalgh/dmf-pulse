# Early independent identity review — not final acceptance

Reviewer: fresh read-only `cts001p_identity_review` agent. Scope: whether accepted private
UUIDv5/transient identities can bind the public P0 UUIDv7 identities without rematching or
changing either accepted lineage. Verdict: no authority blocker; use an authenticated private
binding wrapper. No provider access or code edits were performed by the reviewer.

P0 contains 20 HUMAN_VERIFIED `official_fpl` external club IDs scoped to `2026/27` in
`config/providers/openfootball_historical_team_identity.json`. The strict contract and root
authentication are in `team_strength_governance.py`. Exact joins use those approved IDs, not
display names. DMFP-03 section 24.2 and DMFP-05 section 21.2 prefer approved crosswalks and
trusted exact external identifiers.

Private IDs remain unchanged: team IDs originate in `automatic_inputs._team_uuid`, current
fixtures in `markets.current`, future fixtures in `automatic_rolling_fixture_id`, and the
season-specific EPL competition in `one_command`. The public `FixtureRegistration` contract
requires UUIDv7 and must not be weakened.

Implementation route to verify at the next checkpoint:

1. Authenticate the supplied public fixture registry against the model's registry SHA.
2. Resolve P0 clubs through the exact provider/season/FPL-ID crosswalk.
3. Select the unique public fixture by season and oriented canonical clubs.
4. Call the unchanged public fixture adapter.
5. Seal a private wrapper binding that unmodified bundle to the original private identities,
   cutoff, private identity-map SHA, P0 identity SHA and public registry SHA.
6. Require exact complete bijective horizon coverage, no swaps/collisions, authenticated nested
   data, valid competition/season, and mapping availability by the comparison cutoff.

No claim is made that the two UUID representations are equal. No new canonical identities,
name matching, registry rewrite, baseline/Stage-7 mutation or public validation relaxation is
authorized. A 2025/26 artifact must never be presented as a 2026/27 forecast model.

Authority file hashes:

- DMFP-03: `f3ecc7bb990e4f3ae0dcedb06438e04cd5516b156c9130fdc542dcd09dcd58ab`
- DMFP-05: `de024be01f8e1fdd1bae259ffe9230508870830644da67dc61639cb70cd943dd`
- DMFP-20: `7ed484961cf81af1716db6daa51e6fa05ce2584c33bb04c1d59698e3bf934d72`

This early review does not supply the required final 001P independent-review verdict.
