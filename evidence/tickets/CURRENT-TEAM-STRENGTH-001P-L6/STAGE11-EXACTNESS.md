# L6 D5 exactness rerun

The repository-owned synthetic near-envelope workload was rerun through the real
public Stage-11 service. It contains 31 candidates and 16 retained incoming
candidates. No provider or private input was used.

| Cumulative legal-action cap | Result | Observed legal actions | States | Decision SHA |
|---:|---|---:|---:|---|
| 250000 | `RESOURCE_LIMIT` / `CUMULATIVE_LEGAL_ACTION_LIMIT` / `NO_INCUMBENT` | 250036 | 1623 | failure identity only |
| 524288 | `SUCCESS` | 320610 | 3126 | `f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47` |
| 1048576 | `SUCCESS` | 320610 | 3126 | `f5b3d892d999e399be67c6137726adb54d136ccc73a40699b19f5d1efe5e2f47` |

The governed and high-cap results have byte-equivalent cap-independent decision
semantics: recommendation, no-transfer baseline, root counterfactual and complete
transfer-count frontier. Exact output remains mandatory; no incumbent was
substituted and the candidate universe was not narrowed.

The generated JSON files in this directory are the immutable proof outputs.
