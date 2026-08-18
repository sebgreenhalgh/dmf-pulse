# Rules configuration boundary

RUL-002 authoring fixtures live under `fixtures/rules/RUL-002/` so independent supplied oracles and their byte hashes remain together. `synthetic_complete/` and `reference_2025_26/` may compile and score; `target_2026_27_partial/` remains a deliberately incomplete fail-closed regression fixture.

`fpl-2026-27/` is the source-backed target-season ruleset. Its `VERIFIED`
lifecycle state means the authored values and executable capability closure have
passed engineering verification; it does not mean `ACTIVE`. Production
activation additionally requires a trusted human approval and passing activation
evidence, including completed representative official-match reconciliation.

Compiled outputs are explicit operator artifacts under `artifacts/rules/` and are never resolved through a mutable `latest` alias. Schema 1.1 may compile separately hashed capability review artifacts; capability readiness never weakens the full-season activation gate. An approved VERIFIED ruleset can be activated only into an explicit immutable registry path. No target-season rule is inferred from this directory.
