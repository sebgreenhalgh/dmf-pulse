# CURRENT-FPL-STATE-001C engineering result

## 1. Git

- Parent: `e53ec45badcf00acfdad37dc51fd5d8572d7a505`.
- Branch: `integration/current-fpl/CURRENT-FPL-STATE-001C-operator-manager-state`.
- Final HEAD: `FINAL_COMMIT_CONTAINING_THIS_RESULT`.
- Remote HEAD and exact-SHA CI: pending the single final push.

## 2. Source authority

Manager source is structurally `OPERATOR_DECLARED`; attestation is `HUMAN_ATTESTED`; provider
verification is `NOT_PROVIDER_VERIFIED`. The implementation has no provider transport,
authentication, credential, browser, database, or persistence path.

## 3. FPL binding

Every squad member resolves by exact official FPL element ID through the accepted
`CurrentFplInputBundle`. Player/team identity, position, current price, season, source digest,
target Gameweek identity, cutoff, 001A bundle digest, and a complete consumed-catalogue view digest
are bound. Current prices are catalogue-derived only. Request binding occurs before the local
manager declaration is read.

## 4. Manager squad

The rule-configured squad size, exact position quotas, and maximum-per-club limit are enforced.
Unknown, duplicate, 14/16-member, wrong-quota, and wrong-club states block. No club-quota
grandfathering is inferred.

## 5. Prices

Purchase price is strict positive integer operator state. Current price is 001A-derived. Selling
price is derived through accepted `optimisation.manager_state.selling_price_tenths` using the exact
ACTIVE transfer-rule view. Optional observed selling price must equal the derivation exactly.
Even/odd rises, falls, unchanged prices, float/negative/missing purchase price, catalogue
substitution, observed-price disagreement, and rule-lineage substitution are covered.

## 6. Bank / FT

Bank and free transfers are strict non-negative integer declarations. Free transfers must not
exceed `TransferRules.maximum_free_transfers`; no history is guessed to derive the actual count.
The active tactical rules establish the FPL tenths price unit.

## 7. Lineup

The configured XI and bench sizes, unique complete squad partition, explicit goalkeeper bench
role, outfield bench order, legal position formation, distinct starter captain, and distinct
starter vice-captain are enforced without repair. Starting-XI order is canonical and
non-semantic; bench order remains semantic.

## 8. Chips

The operator must declare every distinct configured token/copy. The result is reconstructed and
validated through the accepted compiled chip bundle and inventory transitions, retaining grant,
copy, window, definition, rules, bundle, and inventory lineage. No chip defaults are invented.
Zero or one rule-valid pending/active non-restoring chip is supported. Active or pending Free Hit
returns explicit `USAGE_INVALID` because restoration-relevant permanent state is unavailable.

## 9. Temporal / rights

Manager target Gameweek, season, and cutoff must equal 001A. FPL usable time, declaration,
attestation, receipt, usability, and cutoff are totally ordered in UTC and post-cutoff state
blocks. The exact inherited manual/private/transient FPL rights boundary is revalidated. Runtime
flags prove no persistence, database, cache, backup, or network use by 001C.

## 10. Disclosure

The complete bundle is private. Its dedicated safe summary exposes counts, timestamps,
verification class, source/rules/chip hashes, and runtime flags only. It excludes owned IDs,
names, clubs, purchase/current/sell prices, bank, free transfers, captaincy, operator reference,
and account identifiers. All repository tests use synthetic data; no real manager state exists in
the tree.

## 11. Semantics

Canonical declaration and final-state hashes are deterministic and path-independent. Non-semantic
squad/XI/chip-token input order is canonicalised; bench order changes both declaration and final
hashes. Verification reconstructs the expected bundle from its embedded declaration plus exact
FPL/rules sources. Player, price, bank, FT, captain, vice, bench, chip, cutoff, rules, FPL source,
and outer-hash tampering all block, including after recomputing the outer hash.

## 12. Focused tests

- Manager-current matrix: **84 passed**.
- Branch-aware executable-surface coverage: **91.67733674775928%** overall (**92% displayed**),
  566/599 statements and 150/182 branches; gate `>=90%`: **PASS**.
- Rights, temporal, price, lineup, chips, semantics, disclosure, and file security: **PASS**.

## 13. Inherited

- 001A / 001B / Stage-11 / Stage-14 / price / current-rules matrix: **409 passed**.
- PostgreSQL 18.4 inherited integration matrix: migrations through `20260807_0006`, **126 passed,
  140 deselected**.
- 001C itself remained database-free.

## 14. Static/build/security

- `uv sync --all-groups --frozen`: **PASS**, 40 packages checked.
- diff, Ruff format, Ruff lint: **PASS**, 661 files formatted and lint clean.
- mypy: **PASS**, 250 source files.
- build: **PASS**, sdist and wheel.
- generic installed wheel: **PASS**, HEALTHY, 291 files, network fetch disabled.
- ODD-005 installed wheel: **PASS**, zero network requests.
- GCS-008 installed wheel: **PASS**, 291 record members.
- repository validation and secret scan: recorded by the final command ledger.

## 15. Final actions

Automatic push CI is intentionally pending until the final evidence/manifests are sealed and one
final commit is pushed. The CI run ID is not committed, so its tested SHA remains the independent
review target.

## 16. Findings

Same-agent adversarial self-review has unresolved P0 = 0, P1 = 0, material P2 = 0, and P3 = 0.
Independent review has not been performed or claimed.

## 17. Status

`CURRENT_FPL_STATE_001C_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

## 18. Next action

`INDEPENDENT_REVIEW_CURRENT_FPL_STATE_001C`
