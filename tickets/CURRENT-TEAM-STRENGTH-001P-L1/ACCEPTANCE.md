# L1 acceptance and execution boundary

Implementation parent: `338571d535d701cbf0251cfeff23dabe171667d3`.
Phase A is not yet an execution approval: publish reviewed code, verify exact
local/remote equality, all mandatory exact-SHA CI jobs and clean worktree first.
The independent final verdict must be
`CLEAR_FOR_CURRENT_TEAM_STRENGTH_001P_L1_ONE_SHOT_EXECUTION`.

The FPL standing purpose is unchanged. The new Odds profile is exactly hash-bound
to the human L1 approval; capability matrix, unresolved rights, account, geography,
terms and zero retention are unchanged. Archived A2 tests explicitly use their
historical authority; A2 runtime against current L1 authority must fail closed.
The generic legacy horizon-probe metadata checker is not a purpose approval and
must not be invoked under this ticket.

## Phase A commands

- `uv sync --all-groups --frozen`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy src/dmf_pulse`
- New L1 and inherited 001P/OpenFootball/Odds/one-command tests, with zero network.
- Branch instrumentation of all new production paths; no numerical/error-path exclusions.
- Inherited full mandatory CI, including repository-required PostgreSQL jobs.
- `uv build --no-sources`; clean installed-wheel check outside source tree.
- `uv run python scripts/generate_repository_manifest.py --ticket PRC-013`
- `uv run python scripts/validate_repository.py`
- `uv run python scripts/scan_secrets.py`
- `git diff --check`

## Phase B, only after every publication gate

Run the standalone `scripts/run_team_strength_l1.py` surface; it is not registered
under ordinary `dmf pulse`. No scheduler, retry wrapper, redirection, tee or output
file. Credentials remain inside the existing local runtime credential providers.

1. `public-preflight --commit <immutable-40-hex> --historical-corpus <approved-public-corpus> --public-artifact-root <public-only-store>`
2. Verify the public summary, current LIVE_OBSERVED artifact, usable time, identity,
   full 380 oriented current EPL fixture registrations, covariance/Hessian and
   FRESH/permitted DEGRADED assessment. A public block leaves private approval unconsumed.
3. On a terminal, `observe --public-readiness <public-ready-json> --readiness-sha256 <expected> --entry-id <operator-entry> --code-sha <exact-green-sha> --approval-reference DMF-CTS-001P-LIVE-RIGHTS-2026-09-22 --execution-attestation CURRENT-TEAM-STRENGTH-001P-L1#ONE-SHOT-2026-09-22 --confirm-one-shot`.
4. Stop after this invocation, success or failure. First attempted FPL/Odds send
   consumes the authorization; each client has exactly one attempt per request.
   The service also rejects a second invocation. There is no automatic process
   restart and no private live artifact/consumption ledger written to disk.

The intended private cutoff is a declared five-minute acquisition window end.
Current source due-completeness is reassessed at that exact cutoff before FPL.
Actual network sends check the real clock; after inputs are acquired they close
permanently, before Stage 7. The inherited final preparation guard can then allow
deterministic computation after the window. A process-local audit hook additionally
blocks unexpected network-backed services after closure. Before/after comparison
counters include actual sends, acquisition counts and denied sends.

OneCommand prepares exactly once. Its callback runs unchanged 001P comparison and
terminates via a private completion exception carrying only the allowlisted summary.
No fake rolling result or third baseline solve is introduced. Production keeps
the default 256 scenarios/seed and exact acceleration; the offline generated-data
vertical slice explicitly uses two draws to keep its test cost bounded, without
mocking Stage 7/8/9/10/11 or adding any production tuning knob.

Only public OpenFootball source/readiness/model objects have a persistence API.
Historical final vintages retain receipt timestamps and explicit origin; the
historical RECONSTRUCTED artifact is never used as the current live model.

No activation, posterior mixtures, R9C player-allocation variant, new dependency,
schema migration, PR, merge, or accepted tag is authorized.
