# Existing decision-stack contract inventory

Inventory captured against parent `7f4254905bccf79cdc282d04f4928cba850276be`.

| Capability | Existing public boundary | Required input | Output / scenario semantics | Rules and configuration |
|---|---|---|---|---|
| Current official FPL | `ingestion.fpl.current.CurrentFplInputService.compile` | Bounded manual bootstrap/fixtures request | Immutable transient current catalogue/fixtures; no network or storage | `fpl_official_private_manual_v1`; current/next GW validation |
| Current manager | `ingestion.fpl.manager_current.CurrentManagerStateService` | Strict operator declaration, current FPL, exact rules/capability | Transient human-attested squad, bank, FT, prices, submitted tactics; no ownership history | Current selling-price, squad, lineup and chip rules |
| Current source coherence | `ingestion.current_state.CurrentUnifiedStateService` | FPL, Odds, identity map, manager, rules | One exact common-cutoff current bundle | Source rights plus exact FULL_SEASON lineage |
| Current markets | `markets.current.CurrentMarketConstraintService` | Unified source and canonical identity view | Per-fixture Stage-8 `MarketConstraintSet`; no player marginals | Packaged Stage-6 and score-baseline policies |
| Manual Stage 7 | `availability.manual_override.build_manual_minutes_override` | Private manual fixture scenario declaration | NOT_MODEL_DERIVED, production-unsuitable team minutes projections | `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1`, LOW/degraded downstream confidence |
| Score distribution | `football_events.service.ScoreDistributionService.project` | Score prior, current market constraints, Stage-7 context | Deterministic joint scoreline distribution | Packaged immutable score-baseline policy |
| Player scoring | `fpl_points.service.FplPointsService.project` | Stage-8 distribution, explicit Stage-7 participation paths, allocation prior/config, rules | Integer player scores with fixture joint matrix and scenario IDs/weights | Accepted rules adapter, MC policy, governed grade-E GW1 donor prior |
| Gameweek assembly | `fpl_points.gameweek.assemble_gameweek` and `gameweek_summaries.build_gameweek_projection` | Fixture results sharing exact outcome-draw IDs/weights | Full Gameweek scenarios, joint matrix and matrix-derived marginals | Same ruleset; explicit shared-draw approximation label |
| Transfer/squad policy | `optimisation.multi_gameweek_service.optimise_multi_gameweek` | Manager ownership state, prices, candidate/action space, scenario tree | Recommended, alternatives, genuine no-transfer baseline, transfers/hits/bank/FT | TEST/REPLAY bounded exact Stage-11 enumerator; current rules views |
| XI/bench/captain | `optimisation.stage10_adapter.Stage10TacticalAdapter` | Candidate squad and full Stage-9 Gameweek scenarios | Exact fixed-squad XI, bench order, captain/vice, autosubs and fallback; retains per-scenario scores | Packaged Stage-10 policy and current one-GW rules view |
| Captain verification | `chips.captaincy.optimise_captain_vice` | Selected XI/tactic and the same Stage-9 scenarios | Joint ordered captain/vice optimum and fallback diagnostics | Ordinary captain multiplier and vice-fallback rules only |
| Report/comparator | No complete current E2E boundary exists; DMFP-18 contract applies | Recommended and no-transfer per-scenario manager scores | Paired gain distribution on identical scenario IDs/weights | UI-002; no independent percentile subtraction |
| Replay/Decision Bundle | No current private vertical-slice bundle exists; DMFP-16 contract applies | Immutable content hashes and injected/frozen inputs | Network-free exact semantic replay without overwriting original | OPS-004; transient/provider retention rights still govern inputs |

No second scorer, simulator, transfer solver, tactical optimiser or captain selector is authorised.
The E2E ticket may add only adapters, orchestration, strict decision/report contracts, and replay.
