# CHIP-014 checkpoint 14.04 — Free Hit

## Capability

Free Hit is evaluated as:

`best legal temporary Free Hit policy - best legal normal transfer policy`

The comparator is not a frozen current XI. Policy candidates are immutable Stage-11/Stage-10
root snapshots on one common scenario set. The accepted Stage-11 root decision can be adapted
through `policy_candidate_from_stage11`; no transfer, selling-price, tactical or autosub rules are
reimplemented in the chip layer.

The result keeps separate:

- gross current-Gameweek gain;
- transfer hits avoided;
- permanent squad damage avoided;
- permanent route/flexibility preserved;
- purchase-price ownership-spell value preserved;
- continuation-value difference;
- net policy value and exercise advantage.

The permanent manager state is restored after the temporary policy with exact squad, bank,
purchase-price ownership history and the configured free-transfer transition. Temporary purchase
cohorts are excluded from permanent ownership history.

## Direct verification

- Focused Free Hit adversarial tests: `23 passed`.
- Complete Stage-14 chip unit confidence: `145 passed`.
- Stage-14 chip-package branch coverage: `93.50%`
  (`393 / 454` branches covered).
- `python -m compileall`: PASS.
- `git diff --check`: PASS before publication.

The focused suite covers:

- Blank Gameweek;
- offensive Double Gameweek;
- defensive Free Hit;
- ordinary transfers beating Free Hit;
- transfer hits avoided;
- valuable purchase-price spell preservation;
- exact permanent squad restoration;
- exact bank restoration;
- exact purchase-price restoration;
- rules-driven free-transfer transition;
- temporary purchases not contaminating permanent ownership cohorts;
- independent best-normal and best-Free-Hit route optimisation;
- Stage-11 adapter lineage;
- token/effect/rules/scenario/hash fail-closed boundaries.

## Status

Checkpoint `14.04` is code- and test-complete locally pending remote fast-forward publication and independent review. The canonical write surface was unavailable in this container session; no force/reset/squash was used.
