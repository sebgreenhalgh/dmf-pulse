# D7 capacity policy

The value `10000000` was used only as the offline discovery ceiling. It is not the
governed runtime policy.

Two repository-owned L7-shaped workloads completed under that ceiling:

| Ordering | Generated policies | Legal actions | Cumulative Pareto retention |
|---|---:|---:|---:|
| baseline-like | 1,432,370 | 1,432,370 | 12,888 |
| shifted-shadow-like | 1,432,641 | 1,432,370 | 13,161 |

Both cases reached 12,888 states; depth 2 alone reached 11,855 states,
1,386,165 legal actions and 327,724 distinct resulting squads. Each node retains a
3/4/3/3 positional incoming screen of 13 players. The later screen changes seven of
those identities while retaining six, using a 35-player repository-owned catalog.
This materially changing, non-disjoint screen dominates the disclosed historical L7
shape without using or reconstructing private identities.

The governed v2 values are:

```yaml
max_generated_policy_candidates: 2097152
max_retained_pareto_candidates: 786432
max_cumulative_legal_actions: 2097152
```

The generated-policy envelope has 664,511 policies of headroom over the larger
shifted-world demand (46.38% of complete demand). The legal-action envelope has
664,782 actions of headroom (46.41%). The retained-frontier cap is not narrowed;
it remains at its prior 786,432 value now under an explicit unit.

All other base-policy limits are unchanged. Existing exact request construction still
raises `max_actions_per_state` and `max_returned_root_candidates` losslessly where the
declared request requires it; the measured stress retained effective values 17,000 and
8,386 respectively.
