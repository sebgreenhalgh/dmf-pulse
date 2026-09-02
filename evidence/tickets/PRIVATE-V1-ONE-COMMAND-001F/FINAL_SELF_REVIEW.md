# Final self-review

| Review question | Finding |
|---|---|
| Smallest complete fix | Three production boundaries changed: Odds commence serialization, current provenance validation and CLI cutoff establishment. |
| Temporal identity | CLI `run_at`, outbound lower bound and current-input cutoff are the same canonical whole-second UTC instant. |
| Generic behavior | Aware whole-second non-UTC values normalize to `Z`; naive and fractional inputs fail closed. |
| Provenance shape | Five required query names plus one optional upper bound only; duplicates and unknowns reject. |
| Bounded window | Both timestamps are canonical and the optional upper bound must be strictly later; target-GW upper-bound policy is preserved. |
| Quality/security | No quality gate, rights policy, authentication path, raw retention rule or credential handling changed. |
| Scope | FPL manager/chips, consensus, score prior, Stages 7-9, optimiser and captaincy are unchanged. |
| Portability | Python/uv only; Windows/Python 3.13 source and lock-pinned external-wheel checks pass. |
| Retention/secrets | No live body, squad, prices, runtime entry identifier or credential is retained or displayed. |
| Activation | Not production active; no PR, merge, tag or provider write occurred. |

No unresolved P0/P1 finding exists in the 001F code or tests. An unconstrained diagnostic install
selected Typer 0.27.2 and exposed a pre-existing private-import compatibility issue; the governed
frozen Typer 0.27.0 graph and 001F wheel/CLI proof pass, and dependencies remain outside this
hotfix. Live verification remains blocked by absent runtime credentials and entry ID. Human
acceptance and independent review remain separate.
