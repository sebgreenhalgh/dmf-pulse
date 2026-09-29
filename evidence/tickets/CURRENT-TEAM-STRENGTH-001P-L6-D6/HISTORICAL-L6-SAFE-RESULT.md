# Historical L6 safe result

This ticket uses only the disclosure-safe L6 terminal record. It neither retains nor
reconstructs private provider input.

| Field | Safe value |
|---|---:|
| failed world | `LEAGUE_BASELINE` |
| rolling phase | `VALIDATE_THREE_GW_RESULT` |
| failure | `OPTIMISER_FAILURE / MULTI_GAMEWEEK_RESOURCE_LIMIT` |
| limit identity | `CUMULATIVE_LEGAL_ACTION_LIMIT` |
| configured cumulative limit | 524,288 |
| first crossing (not complete demand) | 524,297 |
| reachable layer states | 9,249 |
| effective actions per state | 17,000 |
| effective returned-root upper | 8,386 |
| state-expansion cap | 25,000 |
| policy-candidate cap | 250,000 |
| observed maximum combinations | 1,032 |
| Stage 8 / Stage 9 / MC progress | 30/30, 3/3, 3/3 |
| incumbent | none |
| shadow world | never started |

The value 524,297 is classified only as the first batch that crossed the cap. It is
not used as an estimate of complete work.

L1, L2, L3, L4, L5 and L6 are permanently consumed. D6 creates no L7 authority.
