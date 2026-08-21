# Provider drift and fail-closed matrix

| Condition | State | Effect |
|---|---|---|
| Valid required H2H, optional totals valid | PASS | H2H and totals accepted. |
| Valid H2H, totals absent or safely malformed | WARNING / DEGRADED | H2H accepted; totals explicitly absent with one deterministic warning; no invented value. |
| Valid supported material plus isolatable additive market family | WARNING / DEGRADED | `ADDITIVE_UNSUPPORTED_MARKET:<key>` and drift key recorded; family excluded from current semantics and consensus input. |
| Mandatory H2H missing, duplicated, incomplete, conflicting, malformed, or line-bearing | BLOCK_DECISION | Provider-native current input is not produced. |
| Invalid provider/bookmaker/market time or event not prematch at cutoff | BLOCK_DECISION / NOT ELIGIBLE | No current input is eligible. Provider time never becomes `usable_at`. |
| Secret-like unexpected field | BLOCK_DECISION / QUARANTINE | No secret-bearing current input or diagnostic is emitted. |
| Rights denial/unknown for required private use | BLOCK_DECISION | Transport/use is refused. Unknown never becomes allow. |
| Identity ambiguity | UNRESOLVED | No automatic provider-to-canonical mapping in this ticket. |
| Post-cutoff receipt/usable time | NOT ELIGIBLE | Observed evidence cannot be used at the earlier cutoff. |

The additive-market rule does not weaken strict response-envelope, identity, numeric, H2H,
security, rights, or temporal validation.
