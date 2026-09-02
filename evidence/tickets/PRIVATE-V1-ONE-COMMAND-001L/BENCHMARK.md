# PRIVATE-V1-ONE-COMMAND-001L deterministic benchmark

Command:

`python scripts/benchmark_stage10_batch.py --squads 263 --scenarios 256`

The old and new evaluators ran sequentially in one Python process on the same Windows machine.
The generated squads use standard 2/5/5/3 FPL position structure and overlap heavily. Scenario
weights, player points and appearance states are deterministic.

| Measurement | Result |
|---|---:|
| Unique fixed squads | 263 |
| Joint scenarios | 256 |
| Unique appearance states | 26 |
| Retained 001K evaluator | 1,510.7242668 seconds |
| 001L node kernel | 14.8504517 seconds |
| Speedup | 101.7291795x |
| Exact old/new tuple equality | PASS |
| Declared logical scenario operations | 24,440,064,000 |
| Factored expensive state/scenario operations | 2,391,783 |
| Final canonical scenario operations | 67,328 |

The accelerated measurement includes canonical evaluation of each selected tactic. It is below
the five-minute private Stage-10 target without process parallelism. Logical exhaustive-search
counters remain unchanged; the lower factored count describes physical reuse only.

A conservative second run added eight irrelevant signal players that force all 256 global
appearance masks to be unique. Per-squad exact regrouping kept the complete 263-squad accelerated
batch at 14.9435100 seconds; the retained result was sampled exactly for equality. This proves
unrelated-player appearance variation does not defeat the node kernel's tactical reuse.
