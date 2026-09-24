# Test cadence contract

The executable source of truth is `config/testing/cadence.json`; selection is
implemented by `scripts/test_suite.py` and rejects missing deep-assurance modules.

## Fast development

Command: `uv run python scripts/test_suite.py run fast`

The final plan contains 2,117 pure unit/property/contract/security nodes. It
excludes PostgreSQL, migration, integration, and performance markers plus the
explicit assurance/ingestion/markets/optimisation/private-v1 cross-boundary roots
and measured deep modules. Those areas use checkpoint while being changed.

Measured result: 2,117 passed in 217.77 seconds (3m37.77s), selection SHA-256
`d892e3e457efdc2bdbb33cd1198e0f0cc403650cd38150bc9c8a686b02fc95af`.

## Checkpoint

Command: `uv run python scripts/test_suite.py run checkpoint --target <path>`

Targets are explicit and performance tests are excluded. A caller selects the
affected subsystem, its integration/golden tests, and relevant public contracts.

## Full acceptance

Command: `uv run python scripts/test_suite.py run full`

This executes every `not performance` test and then every `performance` test. It
preserves the two complete Phase-1 populations and does not replace mandatory CI.

## Nightly / deep assurance

Command: `uv run python scripts/test_suite.py run nightly`

This repeats 759 deep/performance nodes. Every one remains in full blocking
acceptance; zero correctness tests were moved exclusively to nightly.

## Selection invariants

- Full collection: 5,304.
- Non-performance: 5,300.
- Performance: 4.
- Fast: 2,117.
- Nightly/deep repeat: 759.
- Fast and nightly are explicit convenience/assurance views; full collection is
  still authoritative.
