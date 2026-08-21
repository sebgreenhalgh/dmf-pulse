# GW1-PLY-002 Stage-9 coverage policy

The immutable artifact contains one cell per prior field and group. It is the
canonical machine-readable coverage matrix; this document states the policy.

| Coverage | Fields |
| --- | --- |
| Direct | broad Wyscout assists, yellow cards, clearances, interceptions, fouls conceded, key passes, offsides, pass attempts/completion |
| Derived | nonpenalty goals, red/second-yellow cards, saves, won defending-duel tackles, shot outcomes, won attacking-duel dribble proxy, accurate open-play crosses |
| Role-pooled proxy | own-goal allocation weight; role adjustments fixed at 1 to avoid double-counting already pooled means |
| Generic fallback | penalty weight is uniform; 2017/18 identities cannot imply a current taker |
| Unsupported | inside-box saves, blocks, recoveries, big chances, error-leading events, fouls won, goal-line clearances, being tackled/times tackled |

`being_tackled` remains a typed interface field even though the current
`fpl-2026-27` bonus policy marks it `REMOVED`. The candidate supplies event
frequency baselines only: it does not revive historical BPS coefficients,
convert Wyscout assists into FPL assists, or claim Opta equivalence.
