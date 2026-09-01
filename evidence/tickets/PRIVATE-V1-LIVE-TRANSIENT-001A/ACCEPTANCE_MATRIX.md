# PRIVATE-V1-LIVE-TRANSIENT-001A acceptance matrix

| Requirement | Evidence | Status |
|---|---|---|
| Ordinary current manager path still rejects VERIFIED rules | `test_verified_rules_require_exact_private_authority` | PASS |
| Exact private authority admits only VERIFIED FULL_SEASON rules | Authority validator plus manager/unified-state reconstruction tests | PASS |
| Authority is bound to ruleset, capability, season, approval time and its own hash | Authority hostile tests | PASS |
| ACTIVE behavior remains available without private authority | `test_active_manager_path_is_unchanged` | PASS |
| Private authority cannot attach to ACTIVE or activate rules | Same test plus immutable VERIFIED-status assertion | PASS |
| Original prior and acceptance remain byte-identical and GW1-only | Raw SHA pins in `test_packaged_gw1_resources_remain_byte_exact`, `test_original_binding_remains_gw1_only`, and inherited prior tests | PASS |
| Post-GW1 policy has a distinct identity and stale grade-E/non-acceptance disclosure | Typed sealed carry-forward policy and report assertions | PASS |
| Team changes cannot silently retain an individual profile | Current-team relationship and explicit-fallback tests | PASS |
| Fallback is explicit, deterministic, same-position and lineage-bound | Carry-forward unit tests | PASS |
| Unsupported players never silently zero | Missing/wrong donor failures plus exact fixture coverage | PASS |
| Rights/source failures stop before reading FPL files | Parameterized live-boundary fail-before-read tests | PASS |
| Live mode has no raw/derived/replay/report write option | CLI option introspection and zero-persistence source snapshots | PASS |
| Cache and backup are not implemented | Live request/result and CLI expose no such boundary | PASS |
| Synthetic replay remains unchanged | Complete private suite freeze/replay proof | PASS |
| Current-like FPL through captaincy produces a legal display-only result | `test_current_like_verified_live_transient_full_stack_has_zero_persistence` | PASS |
| Real output distinguishes transient/non-replayable/non-production | Decision and report assertions | PASS |
| Real operator run uses genuine supplied inputs only | Approved input-root inventory | BLOCKED: inputs absent |
| Branch pushed and exact final-SHA CI green | Post-commit external gate | PENDING |

Engineering readiness does not imply independent review, human acceptance, merge, production
activation, or a genuine real recommendation.
