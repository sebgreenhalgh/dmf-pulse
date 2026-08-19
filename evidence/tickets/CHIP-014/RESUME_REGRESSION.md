# CHIP-014 resume confidence regression

## Finding

The resumed checkpoint confidence run exposed a completed-checkpoint defect in the generic
chip compiler. `CAPTAIN/SET_MULTIPLIER` treated `vice_fallback: false` as invalid generic
semantics. That prevented the captaincy policy layer from comparing the declared effect with
the accepted tactical rules view and returning the specific
`CHIP_TC_FALLBACK_MISMATCH` error.

## Remediation

- The generic compiler now accepts either strict boolean value for `vice_fallback`.
- Multiplier domain validation remains fail closed.
- The captaincy evaluator remains responsible for reconciling the compiled declaration with
  the accepted rules view.
- Added an explicit compiler regression proving that `false` is generically compilable; the
  existing captaincy regression proves the downstream mismatch is rejected.

## Focused validation

Command:

```text
PYTHONPATH=src python -m pytest -q --confcutdir=tests/unit/chips \
  tests/unit/chips/test_compiler.py \
  tests/unit/chips/test_captaincy.py \
  tests/unit/chips/test_bench_boost.py
```

Result: `75 passed`; full existing chip confidence: `126 passed`.

This is a correctness remediation only. It does not change the accepted target-season Triple
Captain declaration or any chip inventory/public result contract.
