# Donor reconciliation ledger

| File/capability | Main parent | Readiness donor | LIVE-ODDS-001 decision |
|---|---|---|---|
| `client.py` | Mature rights/quota/retry/evidence client and urllib transport | Retains urllib; joins `h2h,totals`; imports isolated credentials | Retain main client state machine; rewrite a first-class `http.client` transport behind its protocol; retain urllib only as an explicitly selected compatibility/test transport; no fallback. |
| `config.py` / provider JSON | Strict `h2h` allowlist and cost 1 | Strict `h2h,totals` allowlist and cost 2 | Port the donor request surface and cost invariant; retain main strict parsing and bounds. |
| `credentials.py` | Credential protocol/classes embedded in `client.py`; safe default unavailable | Lazy systemd/runtime provider, validation, non-reading configuration hint | Port the narrow donor file and preserve main's final-boundary resolution/error sanitisation. |
| `current.py` | Absent | Provider-native H2H/totals, temporal, rights, provenance and semantic-hash contract; incorrectly blocks every extra market | Rewrite against main parser/config contracts; replace the hard blocker with deterministic additive drift warning/exclusion; retain all critical H2H and cutoff blockers. |
| `parser.py` | Strict bounded parser; all non-H2H keys warned as unsupported and outcome identity was H2H-centric | Treats configured totals as supported and keeps distinct totals lines distinct | Retain main parser architecture and source/semantic hashes; port configured-market recognition and line-aware totals identity; make additive warning taxonomy explicit. |
| `mapping.py` | Later-main explicit canonical mapping | Donor also contains current FPL/Odds identity extensions | Retain main unchanged; exclude donor identity reconciliation. |
| `models.py` | Later-main provider/quota/quality contracts | No material current-input contract change | Retain main unchanged unless a narrow typed transport identifier is required. |
| `service.py` | Later-main rights-gated live-shaped acquisition/evidence path | Defaults to runtime credential provider and joins configured markets | Retain main persistence/lifecycle behavior; port runtime credential default and explicit `http.client` default only. |
| `persistence.py` | Later-main immutable evidence/canonical publication | No relevant donor delta | Retain main unchanged. |
| `live.py` | Absent | Readiness-only GW1 live snapshot composition | Inspect for interfaces/evidence only; deliberately exclude wholesale port to avoid readiness orchestration/database contract replacement. |
| `identity.py` | Absent | Current FPL/Odds team and fixture reconciliation | Deliberately excluded for the next bounded reconciliation unit. |

This ledger will be updated against the final diff. No donor directory, commit range, or branch is
merged or cherry-picked.
