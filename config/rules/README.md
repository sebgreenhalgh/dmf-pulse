# Rules configuration boundary

RUL-002 authoring fixtures live under `fixtures/rules/RUL-002/` so independent supplied oracles and their byte hashes remain together. `synthetic_complete/` and `reference_2025_26/` may compile and score; `target_2026_27_partial/` is deliberately incomplete and cannot score or activate.

Compiled outputs are explicit operator artifacts under `artifacts/rules/` and are never resolved through a mutable `latest` alias. Schema 1.1 may compile separately hashed capability review artifacts; capability readiness never weakens the full-season activation gate. An approved VERIFIED ruleset can be activated only into an explicit immutable registry path. No target-season rule is inferred from this directory.
