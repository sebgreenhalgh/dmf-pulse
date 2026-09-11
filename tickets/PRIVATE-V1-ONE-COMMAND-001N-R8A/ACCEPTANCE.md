# R8A observation-only acceptance

Parent: c60d5b34a7d8922cd274d1ef28648b9e6235d718; CI 34619880451, all 12 jobs
reverified successful before editing. No previous worktree is modified.

The operator script reuses acquire_direct_fpl_snapshot, its target selection and
runtime private input requirements, then invokes one existing OddsClient.fetch.
No accepted equivalent public-only snapshot seam was identified. The script
does not construct manager state, fetch OpenFootball, or invoke Stages 7-11.

Cutoff is the inherited operator approval plus five minutes, rounded down to a
whole second. The request uses the fixed configured EPL/UK/h2h,totals endpoint,
decimal/ISO formats, cutoff lower bound and last official horizon kickoff plus
one second. Retries remain the client's bounded physical attempts, not polling.

Classification reparses the original complete body through parse_odds_payload.
No subset body is fabricated and the strict current-input model is unchanged.
Empty arrays and absent H2H are observations, not accepted current inputs.
Malformed JSON, malformed typed prices/timestamps, duplicates rejected by the
strict parser, and secret-like fields remain typed failures. Parseable malformed
H2H blocks; parseable invalid/unsupported totals remain separate degradation.
Missing required arrays remain strict parser failures; they are not silently filled.

Exact reviewed aliases, orientation and UTC kickoff bind fixtures. Unknown or
unproven outside events conservatively block possibly relevant fixtures rather
than establishing absence. Exact outside-horizon assignments are separate.
Exclusive fixture statuses reconcile; market diagnostics are explicitly overlapping.
Every supported paired half-goal line is observed as its actual line, never merged
or converted to 2.5. This is structural observation, NOT Stage-6 acceptance.

Market time takes precedence over bookmaker fallback. The unchanged authenticated
market freshness policy is assessed at an actual pre-cutoff time; source receipt,
assessment and completed first-classification usability remain separate. Final
verification reconstructs membership and categories from the complete source.

Nonempty success requires actual last cost 2; empty success requires last cost 0.
Actual quota headers and attempt count remain distinct from nominal cost. Invalid
or absent headers, late receipt/usability and source tampering never prove absence.

Safe terminal summary only: no provider strings, prices, entry ID, secrets, raw
body, file export, database, cache or backup. No model acceptance claim is made.

Required gates: focused RED/green and affected ingestion regressions; unchanged
ordinary-source hashes; formatting, lint, strict typing; branch coverage without
lowered thresholds; frozen sync, build and clean installed-wheel verification;
canonical manifests, repository validation, secret scan, git diff --check;
separate read-only independent review with no P0/P1/material P2; publication of
one exact reviewed SHA and full exact-SHA CI. No R8B follows automatically.

Operator command (only existing approved scope and already-present credentials):

    uv run python scripts/probe_horizon_market_coverage.py --entry-id <private-id> --rights-approval-reference <existing-human-approval-id> --confirm-approved-scope

The checked-in July rights profile currently yields NOT_ATTEMPTED before any
credential resolution or transport. Flags cannot upgrade its approval.
