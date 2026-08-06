# NRM-006 Acceptance Contract

NRM-006 is accepted only when every mandatory outcome below is demonstrated from the exact baseline and final clean commit.

## A. Preflight and governance

1. Branch is `stage/A6/NRM-006-odds-normalisation`.
2. Baseline is exactly `e36ea84cda9e80191a9160d037f8e7035477b9b1`.
3. The initial tree is clean except that the exact untracked Pack 1.0 blocker at `evidence/tickets/NRM-006/BLOCKER.md` is permitted; it must be preserved byte-for-byte as prior blocker evidence. The final tree is clean.
4. Pack manifest and detached hashes validate.
5. No live provider request occurs and no real credential is requested, read or stored.
6. The inherited ODD-005 public behavior remains green except where this pack explicitly corrects synthetic provenance and temporal semantics.
7. No future-stage forecasting, minutes, score-grid, player-prop or optimiser logic is introduced.

## B. ODD-005 P1 temporal corrections

1. Parsing, mapping, rights and quality work complete before the activation transaction begins.
2. The activation transaction atomically publishes the canonical market/quote batch and its USABLE lifecycle state under one immutable `publication_batch_id`. If that transaction fails, no USABLE batch exists.
3. Only after successful activation-transaction commit acknowledgement does the publisher sample an injected UTC clock. That post-commit value is the batch `usable_at`.
4. `usable_at` is persisted in a separate immutable post-commit attestation keyed to the publication batch; it is never derived from provider `observed_at`, `received_at`, a pre-commit clock sample or artificial microsecond offsets.
5. Strict database/as-of queries require the committed attestation. If attestation persistence fails, the durable batch remains excluded until repaired; repair may use only a newly sampled, later timestamp and can never backdate eligibility.
6. Receipt before cutoff plus post-commit `usable_at` after cutoff returns `OBSERVED_NOT_USABLE` and is excluded from the earlier as-of query.
7. Every strict replay/promotion carries an explicit UTC `mapping_cutoff`.
8. Fixture/team/operator external mappings use both valid-time and `system_during @> mapping_cutoff` predicates.
9. Fixture schedule observations require attested `usable_at <= mapping_cutoff` with deterministic tie-breaking.
10. Aliases and labels are resolved through their valid/system intervals as of the same cutoff.
11. Mapping-plan approval/evidence time and evidence class are persisted in lineage.
12. A mapping, alias or fixture correction approved after cutoff cannot change an earlier strict-information replay.

## C. ODD-005 P2 hardening

1. Synthetic fixture evidence uses `synthetic_fpl` or explicit TEST_ONLY provenance and cannot create a HUMAN_VERIFIED/production-authoritative `official_fpl` mapping.
2. Existing production `official_fpl` mappings remain possible only from permitted official/manual evidence.
3. HTTP 429 never immediately retries. Every fake response intended to provide valid quota evidence includes the inherited complete header set: `x-requests-remaining`, `x-requests-used` and `x-requests-last`.
4. Missing one or more required quota headers remains non-retryable `SOURCE_UNAVAILABLE`; NRM-006 does not weaken the inherited three-header rule or invent absent quota evidence.
5. A valid integer `Retry-After` delta from 1 through 60 seconds is honored through an injected sleeper when retry budget and total deadline permit.
6. Missing/invalid `Retry-After` uses the configured deterministic bounded delay; retry remains capped.
7. Sleeper calls, delays and attempts are test evidence; acceptance performs no real sleep or network call.
8. Same numeric odds at different retrieval/source-snapshot times create distinct immutable observation events.
9. Same-value duplicate outcomes inside one payload may be collapsed only with warning `DUPLICATE_OUTCOME_DEDUPED` and a recorded duplicate count.
10. Conflicting duplicate outcomes still quarantine.
11. Mapping valid intervals come from explicit mapping-plan/context evidence. No application literal hard-codes 2026/27 dates.
12. Globally scoped operator mappings use an explicit open-ended or provider-guaranteed validity policy.

## D. Mathematical boundary and exact policy

1. Input odds remain source-scale Decimal strings and are strictly greater than one.
2. Internal calculation uses local Decimal context precision 60 and `ROUND_HALF_EVEN`; it does not mutate global Decimal context.
3. Raw implied probability is exactly `1 / decimal_odds` before public quantisation.
4. Booksum is the sum of raw implied probabilities; overround is booksum minus one.
5. Proportional probability is `q_i / sum(q)`.
6. Power probability uses the unique positive exponent `alpha` satisfying `sum(q_i ** alpha) = 1`.
7. The power solver uses the frozen bracket and exactly 256 Decimal bisection iterations in `09_POWER_AND_PROPORTIONAL_NUMERICAL_CONTRACT.md`.
8. Public probabilities use exactly 12 fractional digits.
9. Vector rounding uses HALF_EVEN then assigns any 12-decimal residual to the largest unrounded probability; ties use HOME, DRAW, AWAY order. Public complete vectors therefore sum exactly to `1.000000000000`.
10. The power result is the primary `market_probability`; proportional is always retained as baseline/sensitivity.
11. Explicit power numerical failure falls back to proportional, emits `POWER_FALLBACK_PROPORTIONAL` and caps confidence at C.
12. No Shin, learned calibration or hidden weighting is present.

## E. Completeness and operator grouping

1. Only COMPLETE full-time pre-match HOME/DRAW/AWAY books are normalised.
2. Each canonical operator is normalised independently.
3. Quotes from different operators are never combined into one de-vigging book.
4. An incomplete, suspended, unsupported, unavailable, stale, rights-blocked or quality-blocked book is excluded with a typed reason.
5. Provider duplicates do not increase canonical operator count.
6. The latest eligible complete book per operator is selected with `usable_at <= as_of` and deterministic tie-breaking.
7. No stale-fill combines outcomes across different observation books.
8. One-sided/nonexclusive player markets are typed unsupported and never forced to sum one.

## F. Consensus, uncertainty and confidence

1. Primary consensus is the equal-weight arithmetic mean of eligible canonical operators' POWER vectors.
2. Technical provider count and canonical operator count remain separate.
3. Operator disagreement is maximum pairwise total-variation distance between primary operator vectors; zero with fewer than two operators.
4. Method disagreement is the maximum total-variation distance between POWER and PROPORTIONAL for any eligible operator.
5. `market_disagreement` is the maximum of operator and method disagreement.
6. Outcome lower/upper bounds are the componentwise envelope of the public POWER and PROPORTIONAL operator vectors.
7. Freshness age uses provider/operator `observed_at`, not `received_at` or `usable_at`.
8. Quotes older than the configured 1,800 seconds at `as_of` are stale and excluded.
9. Confidence grades follow only the frozen versioned configuration; happy path is grade B.
10. Any exclusion, fallback or warning produces status DEGRADED when at least one eligible book remains.
11. No eligible complete book produces INSUFFICIENT, no invented probabilities and CLI exit 2.

## G. Persistence, lineage and deterministic replay

1. Normalisation policy is versioned and hash-addressed.
2. Every operator result and consensus stores source observation IDs, as-of time, mapping cutoff, code commit, policy ID/hash, input signature and result hash.
3. Input signature is deterministic over sorted immutable observation IDs, as-of, mapping cutoff, policy hash and code identity.
4. Repeating the same exact run reuses the immutable result.
5. A new source observation, even with the same odds, creates distinct lineage/input signature; an equal semantic result may share result content hash but not erase the new run/evidence.
6. A changed/corrected source observation or policy creates a new result and never updates the prior result.
7. Database rows are immutable after publication.
8. Cache reuse requires exact dependency signature; fixture/Gameweek/latest aliases alone are forbidden.
9. As-of output is stable after later observations, mappings or fixture corrections.

## H. Database and migration

1. New Alembic revision descends from `20260725_0004` and is manually reviewed.
2. Clean base to head upgrade passes.
3. ODD-005 head to NRM-006 head passes.
4. Downgrade to `20260725_0004` and re-upgrade pass.
5. Offline SQL contains no credentials or provider bodies.
6. PostgreSQL 18.4 only; no SQLite substitute.
7. Database constraints/triggers enforce probability range, complete-vector identity, lineage, unique input signature and immutability where relationally feasible.
8. Concurrency tests cover duplicate normalisation-run creation and same-source correction races.
9. Schema fingerprint is deterministic.

## I. Public CLI/API and packaging

1. Approved library interfaces match the ticket and compact contracts.
2. `dmf market normalise` supports canonical or explicit external fixture reference, season, as-of and JSON output.
3. Success/degraded returns exit 0; insufficient returns exit 2; rights/quality/temporal block returns exit 4; unexpected failure returns exit 1.
4. CLI and library outputs are schema-valid and semantically identical.
5. Installed wheel runs ingestion replay, observation query and normalisation outside the source tree.
6. No public raw-odds redistribution endpoint is added.

## J. Quality, evidence and review archive

1. Ruff/format, strict mypy, unit, property, contract, golden, security and PostgreSQL integration tests pass with zero skips.
2. Full inherited suite passes.
3. Overall branch coverage is at least 90%.
4. Critical temporal mapping, usable-at, 429, completeness, proportional, power, consensus, persistence and CLI branches are at least 95%; core mathematical functions are 100% branch covered.
5. Every literal acceptance command is actually run and recorded.
6. Structured result says COMPLETE only with zero unresolved P0/P1 findings.
7. Review ZIP has at most 20 root files, no nested entries, valid CRC, manifest and detached hashes.
8. Review ZIP includes the complete human-authored patch from baseline.
9. Final commit, tests, coverage, migration head, payload SHA and archive SHA are recorded.

Any failed mandatory item yields BLOCKED or FAILED, not COMPLETE.
