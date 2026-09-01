# Required-test acceptance matrix

`PV1 service` means `tests/unit/private_v1/test_service.py`; `PV1 coherence` means
`tests/unit/private_v1/test_input_coherence.py`; `PV1 artifacts/contracts/CLI` means the other
private-v1 test modules. Inherited locators remain the controlling implementation tests.

| # | Requirement | Proof | Status |
|---:|---|---|---|
| 1 | Wrong target GW fails | PV1 coherence `test_wrong_target_gameweek_and_mixed_cutoff_fail` | PASS |
| 2 | Stale fixture set fails | PV1 coherence `test_fixture_set_must_be_exact[stale]` | PASS |
| 3 | Mixed cutoffs fail | PV1 coherence `test_wrong_target_gameweek_and_mixed_cutoff_fail` | PASS |
| 4 | Missing fixture fails | PV1 coherence `test_fixture_set_must_be_exact[missing]` | PASS |
| 5 | Duplicate fixture fails | PV1 coherence `test_fixture_set_must_be_exact[duplicate]` | PASS |
| 6 | Manager player must be canonical | PV1 coherence `test_manager_and_candidate_require_exact_canonical_player_ids` | PASS |
| 7 | Stale team fails | PV1 coherence `test_stale_team_membership_and_fuzzy_identity_fail` | PASS |
| 8 | Fuzzy matching impossible | UUID-only contracts in the same test | PASS |
| 9 | Duplicate squad fails | inherited current-manager validation/tamper suites | PASS |
| 10 | Malformed manager artifact fails | current-manager boundaries plus PV1 strict JSON loader/CLI | PASS |
| 11 | Tampered manager artifact fails | `test_fpl_current_manager_tamper.py` and unified verification | PASS |
| 12 | No secret/private public evidence | PV1 service report and coherence serialization assertions | PASS |
| 13 | Manual Stage 7 reaches decision | PV1 service full-stack execution/replay | PASS |
| 14 | Empirical Stage 7 where a valid fixture exists | parent `test_current_player_allocation_port.py`; no valid empirical current execution fixture exists in this ticket | PASS-CONDITIONAL |
| 15 | Stage 8 is team-score authority | PV1 service lineage plus inherited score-distribution/port suites | PASS |
| 16 | Stage 9 is canonical scorer | PV1 service invokes `FplPointsService`; inherited port integration | PASS |
| 17 | Player scenario points integer | explicit PV1 service matrix assertion | PASS |
| 18 | Deterministic player IDs | canonical joint-matrix/player-map assertions | PASS |
| 19 | Valid scenario weights | positive and normalized PV1 service assertions | PASS |
| 20 | Missing player never becomes zero | exact universe validators and inherited player-prior tests | PASS |
| 21 | No fixture disappears | exact three-fixture result/lineage assertions | PASS |
| 22 | Prior provenance linked | per-fixture binding and prior/acceptance lineage assertions | PASS |
| 23 | Exactly 15 selected | PV1 service | PASS |
| 24 | Position composition | PV1 service asserts 2/5/5/3 | PASS |
| 25 | Max-club rule | PV1 service and inherited exact optimiser | PASS |
| 26 | Budget feasible | exact Stage-11 validation | PASS |
| 27 | Bank correct | nonnegative state-after bank plus inherited state tests | PASS |
| 28 | Selling-price semantics | `test_multi_gameweek_state.py` and contract-hardening suites | PASS |
| 29 | Outgoing is owned | PV1 service conditional assertion and Stage-11 transition validation | PASS |
| 30 | Incoming not owned | PV1 coherence and service conditional assertion | PASS |
| 31 | No duplicate player | PV1 resulting-squad assertion and Stage-11 contracts | PASS |
| 32 | Transfer count legal | candidate maximum plus Stage-11 rules | PASS |
| 33 | Free-transfer calculation | `test_multi_gameweek_state.py` | PASS |
| 34 | Hit cost correct | Stage-11 state tests and paired reconciliation | PASS |
| 35 | No-transfer legal | exact no-action baseline required by service | PASS |
| 36 | Optimiser can select no transfer | full-stack synthetic optimum is `NO_TRANSFER` | PASS |
| 37 | Exactly 11 starters | PV1 service | PASS |
| 38 | One starting goalkeeper | PV1 service | PASS |
| 39 | Legal formation | exact Stage-10 result; synthetic result `5-4-1` | PASS |
| 40 | Bench is complement | PV1 service set equality | PASS |
| 41 | Bench goalkeeper semantics | PV1 service | PASS |
| 42 | Bench ordering legal | exact Stage-10 adapter and PV1 service | PASS |
| 43 | Captain starts | PV1 service | PASS |
| 44 | Vice starts | PV1 service | PASS |
| 45 | Captain differs from vice | PV1 service | PASS |
| 46 | Captain applied once | explicit application-count assertion | PASS |
| 47 | Vice fallback semantics | `tests/unit/chips/test_captaincy.py` plus captain hash verification | PASS |
| 48 | No chip multiplier | explicit `NO_CHIP` decision/warning/assertion | PASS |
| 49 | Same upstream scenarios | paired Stage-10 scenario ID/outcome-draw equality | PASS |
| 50 | Baseline retains original squad | Stage-11 canonical no-transfer baseline | PASS |
| 51 | Baseline reoptimizes tactics | baseline exact Stage-10 source/assertions | PASS |
| 52 | Rows aligned | explicit recommended/baseline key-set equality | PASS |
| 53 | Hit only on action | paired comparison reconciliation | PASS |
| 54 | Net uplift exact | arithmetic plus Stage-11 objective equality | PASS |
| 55 | No uplift selects no transfer | synthetic decision has zero uplift and `NO_TRANSFER` | PASS |
| 56 | Outperformance uses coherent paired rows | paired gain PMF built from aligned Stage-10 scenario scores | PASS |
| 57 | Identical bundle/code/seed replays | PV1 service exact decision/report equality | PASS |
| 58 | Manifest stable | PV1 contract stable sealing assertion | PASS |
| 59 | Changed manager changes manifest | PV1 coherence `test_every_required_upstream_change_changes_the_replay_manifest` | PASS |
| 60 | Changed market changes manifest | same test | PASS |
| 61 | Changed Stage 7 changes manifest | same test | PASS |
| 62 | Changed prior changes manifest | same test | PASS |
| 63 | Changed seed/config changes manifest | same test | PASS |
| 64 | Replay needs no network | installed-wheel replay passed with DNS/socket guard | PASS |
| 65 | Installed-wheel replay outside source | dedicated exact frozen-environment proof | PASS |
| 66 | Temporary path irrelevant | relocated bundle equality and no path bytes in manifest | PASS |
