# CHIP-014 checkpoint 14.07 — service, replay, CLI and artifacts

## Published capability

The checkpoint capability commit is
`6583a0d8c7a69a07668cbd53db99b9119a7f89d5`. It was pushed to
`stage/A14/CHIP-014-chip-optimisation`, fetched back, and independently resolved
as both local `HEAD` and the canonical remote ref. Its merge-base with the
immutable Stage-14 parent is
`a8796d4edacea4c87ee6461d381f4df87e1ef39c`.

## Capability

Checkpoint 14.07 supplies the public vertical slice over the accepted Stage-14
domain modules:

- a shared application service composing current chip evidence with the finite
  inventory scheduler;
- sealed request, decision, lineage and probability-diagnostic contracts;
- full rules/bundle/inventory/scheduler/scenario/cutoff/feature/leakage/price/
  continuation/code/seed lineage;
- explicit gross gain, continuation value, policy cost, opportunity cost and
  exercise advantage rather than an opaque score;
- Stage-13 limitation propagation without promotion;
- content-addressed decision artifacts with independent recomputation on load;
- sequential replay that executes only the frozen root action and treats the
  future schedule as advisory before state transition and re-solving;
- a Typer `dmf chips` surface for rules, inventory, captaincy, chip values,
  comparison, explanation, scheduling, backtesting and validation;
- deterministic golden fixtures and contract, property, integration, replay,
  temporal-leakage, tamper, CLI and performance tests.

## Defect found during validation

The first focused run exposed a Windows-only test defect: a text-written
sidecar used platform newline translation while the artifact reader correctly
required canonical bytes. The test now writes the canonical ASCII sidecar
bytes directly. No product behavior was weakened.

The first static run also exposed inherited Stage-14 Python 3.13 typing/style
debt in the generic captaincy and Bench Boost callables plus a mutable local
name collision in captaincy. Those callables now use PEP 695 type parameters,
the selected score tuple has an unambiguous identity, and strict mypy passes.

## Direct verification before publication

- Focused 14.07 test matrix: `62 passed in 8.81s`.
- Ruff lint for the complete chip package, 14.07 CLI and focused tests: PASS.
- Strict mypy for `src/dmf_pulse/chips` and `src/dmf_pulse/cli/chips.py`: PASS
  (`17 source files`).
- Ruff formatting for the changed scope: PASS after deterministic formatting.
- Compileall for the chip package and CLI: PASS.
- `git diff --check`: PASS.

## Remote verification

After publication, `git fetch origin stage/A14/CHIP-014-chip-optimisation`
resolved both `HEAD` and the remote branch to
`6583a0d8c7a69a07668cbd53db99b9119a7f89d5`. Direct remote tree inspection
confirmed `service.py`, `replay.py`, `cli/chips.py`, and the installed vertical
slice test are present.

## Status

`COMPLETE / REMOTE`. This checkpoint is not final Stage-14 acceptance. The
complete Stage-14 adversarial review, repository-wide validation, final
evidence, recovery/transport cleanup and draft PR remain separate work. No
merge, tag or human acceptance occurred.
