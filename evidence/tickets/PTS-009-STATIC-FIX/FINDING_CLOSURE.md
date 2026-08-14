# PTS-009 static finding closure

| Finding | Closure |
| --- | --- |
| F1 | Production `ACTIVE` rules load only from a complete canonical Stage-2 activation directory; receipt, manifest, child hashes, verified-to-active linkage, and in-bundle approval are cross-checked. Forged external approvals and receipt/manifest tampering fail closed. |
| F2 | Participation rows are checked against the actual Stage-7 player/team/position, minute range and PMF bin, role probabilities, and exact on-pitch interval. |
| F3 | Duplicate fixture IDs fail before sorting/aggregation and are rejected by the serialized Gameweek scenario model. |
| F4 | New successful results serialize their Monte Carlo policy. Assurance recomputes diagnostics, summaries, the full matrix/dependence, normalized weights, and requires a non-null semantic result hash; old policy-less artifacts return a recomputation-required error. |
| F5 | BPS competition ranking receives only players with positive official minutes; zero-minute rows have no rank or tie flag. |
| F6 | Scope assurance resolves the parent-to-working-tree Git diff, compares it with `CHANGED_FILES.txt`, and applies fail-closed scope rules to the real paths. |

The Stage-9 status remains review-pending; no merge or self-acceptance is performed here.
