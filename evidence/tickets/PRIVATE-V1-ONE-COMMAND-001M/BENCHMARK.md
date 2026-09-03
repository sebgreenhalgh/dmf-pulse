# PRIVATE-V1-ONE-COMMAND-001M deterministic performance evidence

The repository-owned synthetic private fixture was run three times sequentially on the immutable
001L parent and three times on 001M in separate clean worktrees on the same Windows host.

| Measurement | 001L parent | 001M |
|---|---:|---:|
| Runs | 3 | 3 |
| Seconds | 8.332829, 8.296368, 8.283919 | 8.381639, 8.325914, 8.289917 |
| Median | 8.296368 s | 8.325914 s |

The observed median addition was 0.029546 seconds, or approximately 0.36%. This is informational
wall-clock evidence, not a fragile CI threshold. The stronger regression oracle uses a counting
Stage-10 evaluator and proves transfer-frontier selection performs zero additional exact tactical
evaluations after the governed candidate family has been evaluated. Selection is one deterministic
linear grouping pass over those retained candidates; report construction is bounded by the small
number of available transfer counts and the existing Stage-9 scenario set.
