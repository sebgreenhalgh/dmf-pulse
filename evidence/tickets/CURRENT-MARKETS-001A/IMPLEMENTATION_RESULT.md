# CURRENT-MARKETS-001A implementation result

## 1. Git boundary

- Exact architectural parent: `4eda6fe9ba0db917ac09bf9a877b1a31c6c3f9fb`.
- Branch: `integration/current-markets/CURRENT-MARKETS-001A-transient-market-constraints`.
- Work was performed in a separate clean worktree. The pre-existing dirty
  CURRENT-AVAILABILITY-001A worktree was not modified.
- Final implementation commit and exact-SHA CI are reported by the handoff after push because a
  commit cannot contain its own SHA and no post-CI evidence commit is permitted.

## 2. Authority and predecessor reconciliation

The implementation resolved A3, A5, A6 and A8 through
`specs/manifests/authority_manifest.json` and preserved accepted DAT-003, LIVE-ODDS,
CURRENT-FPL-STATE-001B/001D, Stage-6 normalisation/consensus and GCS-008 market-constraint
contracts. It did not modify accepted predecessor implementations or policy values.

The accepted score service still requires explicit home/away goal rates and an accepted
`Stage7MinutesContext`. No accepted current source of those goal rates exists at the pinned
parent. The exact downstream blocker is therefore `NO_ACCEPTED_CURRENT_SCORE_PRIOR`; no score
prior, fake minutes context or full GCS-008 call was introduced.

## 3. Exact current source binding

`CurrentMarketConstraintRequest` binds the complete 001D unified semantic identity, full FPL
representation, 001B identity-map semantic identity, Odds market identity, Odds provider
provenance, Odds identity semantic identity, canonical identity-view hash, Stage-6 market policy,
confidence-gate policy and GCS-008 constraint policy. A separate exact Odds-quality digest binds
accepted upstream exclusions that are intentionally absent from the 001D market-only digest.

The service revalidates the supplied 001D bundle, reconstructs its semantic hash and requires a
fresh exact request. Price, totals-line, canonical mapping and source substitutions change the
appropriate nested and output identities; stale requests fail closed.

## 4. Canonical identity

The product resolver performs only SQLAlchemy `SELECT` statements. For every target fixture it
requires an accepted official-FPL fixture external identifier and an accepted Odds event external
identifier to resolve independently to the same existing DAT-003 canonical fixture UUID. It also
requires existing global bookmaker-key mappings to active canonical operator UUIDs. Missing,
ambiguous or conflicting rows fail as disclosure-safe `CANONICAL_IDENTITY_UNAVAILABLE`.

No canonical UUID is invented by product code. UUIDv5 values exist only for private transient
Stage-6 adapter observations and are never represented as canonical fixtures, providers or
operators. A real PostgreSQL integration proof showed identical canonical/entity/operator/
provider table counts before and after resolution and market construction.

## 5. Fixture selection and orientation

Target fixtures are selected exclusively from the accepted 001B fixture mappings embedded in
001D. Each mapping is checked against the exact FPL fixture identity, provider-event identity,
home/away teams, kickoff and binding hash already reconstructed by 001D. Unrelated provider events
remain allowed and are ignored by current-market construction.

## 6. H2H consensus

Provider-native accepted `HOME`, `DRAW`, `AWAY` prices are adapted into private transient
`ExclusiveOutcomeQuote` objects and passed to the unchanged accepted Stage-6
`evaluate_market_consensus`. Stage-6 power de-vig, proportional sensitivity, freshness,
equal-operator consensus, bounds, disagreement, confidence and exclusion behavior are retained.

Multiple provider aliases mapped to one canonical operator are collapsed before Stage-6
evaluation. A deterministic newest alias is selected, duplicate weighting is recorded, and tied
conflicting price vectors quality-block that operator.

## 7. Totals consensus

The narrow totals adapter accepts only complete full-time `OVER`/`UNDER` pairs on exact
nonnegative half-goal lines already present in the accepted 001D Odds object. It uses a 60-digit
`Decimal` context, 256-step power root solve, proportional sensitivity, exact 12-place public
complements, equal canonical-operator weighting, public-vector envelopes, freshness,
disagreement and the accepted confidence-gate identity. Unsupported quarter lines and incomplete
pairs cannot enter a structurally valid source and fail closed under hostile construction.

## 8. Stage-8-compatible constraints

The unchanged accepted H2H-to-constraint adapter creates the three 1X2 constraints. Each eligible
totals line creates complementary over/under constraints with exact probabilities, uncertainty,
confidence-derived weights and complete source hashes. The combined `MarketConstraintSet` is
passed through the accepted GCS-008 family-cap implementation.

## 9. Readiness

Each exact target fixture is classified independently:

- `MARKET_READY`: eligible H2H plus at least one eligible totals line;
- `H2H_ONLY_DEGRADED`: eligible H2H and no eligible totals line;
- `BLOCKED`: no eligible H2H, with no usable constraints published.

The synthetic multi-fixture family proves one fixture may degrade or block without misclassifying
another ready fixture.

## 10. Cutoff and freshness

Market evidence is evaluated at the latest of the accepted 001D decision-information time and
canonical-identity resolution time. The 001D information cutoff remains preserved separately.
The target deadline is never used as the market observation time. Stale and future observations
are excluded, and all published constraint `usable_at` values are at or before their set `as_of`.

## 11. Rights and runtime

The output remains `PRIVATE`, `TRANSIENT_IN_MEMORY`, non-persistent and non-public. Raw storage,
derived storage, cache, backup, public display and redistribution remain denied. Product market
construction performs no network or database access. The separately invoked identity resolver may
read DAT-003 and records that fact, but performs no insert, update, delete, flush or commit.

## 12. Disclosure

Ordinary summaries expose only target Gameweek, cutoff, fixture/readiness counts, aggregate
eligible-operator and totals-line counts, confidence-grade counts, runtime flags and the unified
semantic hash. Public error objects, messages, `str` and `repr` contain no provider event IDs,
team strings, bookmaker keys/names, raw prices, manager state or canonical mapping internals.

## 13. Focused acceptance

- Ticket-owned focused suite: **32 passed**.
- Branch-aware focused product coverage: **92.3154701718908%**.
- Covered product statements: **724/767**; covered branches: **189/222**.
- Material mutation, cutoff, duplicate weighting, source substitution, disclosure, runtime,
  deterministic ordering and model-invariant branches were exercised.

## 14. Inherited acceptance

- LIVE-ODDS, 001B, 001D, Stage-6 markets, GCS-008 mathematics/constraints and DAT-003 unit matrix:
  **522 passed**.
- Inherited DAT-003 PostgreSQL and migration matrix: **90 passed**.
- New real PostgreSQL current identity/read-only proof: **1 passed**.

## 15. Static and build acceptance

- Frozen sync: **PASS**, 40 packages checked.
- Diff check: **PASS**.
- Ruff format: **PASS**, 674 files.
- Ruff lint: **PASS**.
- mypy: **PASS**, 252 source files.
- Build: **PASS**, `dmf-pulse` 0.2.0 sdist and wheel. The sandboxed Windows launcher was denied
  before execution; the identical approved host build passed.

## 16. Wheel acceptance

- Generic clean installed wheel: **PASS**, 293 wheel members.
- ODD-005 clean installed wheel: **PASS**, zero network requests.
- GCS-008 installed wheel: **PASS**, 293 record members and all required resources.
- CURRENT-MARKETS installed wheel: **PASS** from an offline environment outside the repository;
  request binding, two ready fixtures, accepted H2H, four totals lines, constraints, verification,
  safe summary and zero network requests were exercised.

## 17. Security and repository acceptance

Repository validation, canonical manifests and secret scanning are sealed after the final evidence
content. No real credential, provider call, real current private data, current-market persistence,
score projection, player model, points calculation, optimisation, PR, merge or production action
was performed.

## 18. Adversarial findings

Same-agent adversarial review records unresolved P0 = 0, P1 = 0, material P2 = 0 and P3 = 0.
The detailed inspection is in `FINAL_SELF_REVIEW.md`. Independent review remains mandatory.

## 19. Status

Subject to the final exact-SHA automatic CI run:

`CURRENT_MARKETS_001A_IMPLEMENTED_PENDING_INDEPENDENT_REVIEW`

Next action:

`INDEPENDENT_REVIEW_CURRENT_MARKETS_001A`
