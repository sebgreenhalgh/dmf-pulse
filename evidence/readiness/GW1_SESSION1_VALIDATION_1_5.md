# GW1 Checkpoint 1.5 — Session-1 operator workflow validation

## Scope and identity

- Canonical branch — `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Starting accepted remote SHA — `b557d1c52604817415b414f8414b938eaa3f69ac`.
- Capability commit — `PENDING_PUBLICATION`.
- Linux validation workflow — `PENDING_PUBLICATION`.
- Real credentialled provider call — `OPERATOR_CHECKPOINT`.

## Implemented vertical slice

- One application service compiles current manually captured official-FPL
  bootstrap/fixtures and retrieves current provider-native EPL `h2h` odds in the
  same process.
- The full provider response remains governed by the accepted live-odds evidence
  boundary. The working odds input is transparently scoped to the inclusive
  minimum/maximum official target-Gameweek kickoff window; source and excluded
  event counts are retained in the transient contract.
- One deterministic private review template exposes exact, case-sensitive
  candidates only. It never chooses an alias or fixture automatically.
- The operator must enter one team ID for every provider team, one fixture ID for
  every provider event, and the complete template SHA-256.
- Accepted Checkpoint-1.4 team and fixture resolvers construct a complete
  one-to-one `FPL_ODDS_IDENTITY_MAP` in memory.
- `SESSION1_DOWNSTREAM_INPUT` binds the actual operator approval time as
  `decision_information_at`; the official deadline remains a ceiling and is not
  treated as evidence that later information was observed.
- CLI stdout contains only a safe completion summary. The private review is
  displayed on stderr with an explicit no-persistence warning. No FPL raw body,
  derived bundle, mapping plan, identity map, or downstream object is written to
  a database or file.

## Hostile review and remediation

### P0

- None found.

### P1

1. A provider response can contain later upcoming EPL events outside the target
   Gameweek, which would make the otherwise exact resolver operationally unusable
   or tempt an unsafe manual deletion. Remediation: derive an explicit target-GW
   time window only from official FPL fixtures, filter transiently before review,
   report source/excluded counts, and retain fail-closed exact coverage inside
   the window.
2. The accepted source contracts use the official deadline as their maximum
   information cutoff. Without a separate actual decision time, a downstream
   consumer could misread that future ceiling as observed information.
   Remediation: bind the post-review UTC approval time as
   `decision_information_at`, validate it against source usability/deadline and
   identity-map decision time, and include it in the downstream semantic hash.
3. A deserialized downstream object initially trusted some nested source hash
   labels without independently recomputing the FPL semantic/identity view, odds
   provenance/identity view, and deterministic review template. Remediation:
   independently recompute all source bindings plus event-scope counts and reject
   tampered lineage before accepting the public downstream contract.

### P2 / P3

- No unresolved P2 or P3 finding is recorded for this bounded checkpoint.

## Local validation

- New Session-1 service/CLI tests — `14 passed`.
- Focused and inherited FPL/Odds/identity/CLI tests — `135 passed, 1 deselected`.
  The deselected test is the accepted Windows symlink test, which requires a host
  privilege unavailable in this environment and remains enabled on Linux CI.
- New service plus affected CLI branch-aware coverage — `96%` total:
  `session1.py 98%`, `ingest_cmd.py 93%` (`36 passed`).
- Disposable PostgreSQL 18.4 migration plus live-odds and source-rights retention
  regressions — `18 passed`; the disposable container was stopped and removed.
- First-party secret scanner — `PASS`, `finding_count=0`.
- Secret-scanner regressions — `22 passed`.
- Ruff format — `PASS`, `508 files already formatted`.
- Ruff lint — `PASS`.
- Strict mypy — `PASS`, `193 source files`.
- Canonical source/wheel build — `PASS`, `dmf-pulse 0.2.0`.
- Clean disposable wheel CLI smoke — `PASS`; installed
  `dmf ingest session1 run --help` exposes the implemented command and no API-key
  option.
- Workflow YAML parse — `PASS`.
- `git diff --check` — `PASS`.
- Repository validation — `FAIL`, `105 errors`, because the branch-wide active
  GCS-008 current manifest predates accepted rules and GW1 branch history. The
  validator's generated report side effect was removed. This known branch-wide
  acceptance debt is not promoted to PASS and remains a final engineering gate.

## File hashes before capability publication

- `src/dmf_pulse/ingestion/session1.py` —
  `1b10c3776c0825ce15d05abcd9b55a65c4e56922c6e329219bf23f97dfcb5b63`.
- `src/dmf_pulse/cli/ingest_cmd.py` —
  `8b38ce1e53b56ce0fe39fb43490a5948929f6db7d7a8112696ac0e3c8bf88b76`.
- `tests/unit/ingestion/test_session1_current_input.py` —
  `640dbe659a9d7b5a4eda380f6fe3f64dab169d0b75ef52f39c0276023a777fed`.
- `tests/unit/cli/test_session1_operator_workflow.py` —
  `800970557f33107222b745ffa157ac1cd84be36da612f0debb1cf292f0f7d07c`.
- `docs/operations/gw1_session1_current_input.md` —
  `5cf94a2dd332ecdf6f859748cf775fa7c52972691a263c535d5231f5b2c4e327`.
- `.github/workflows/gw1-checkpoint-1-5-validation.yml` —
  `12ad17c00e758df5759e1416652f17e90e2443c0660bcb5dc0bdfa8a25529a0a`.

## Status

- Local engineering result — `PASS`.
- Checkpoint 1.5 — `IN_PROGRESS` pending capability publication, Linux workflow
  PASS, evidence attestation, push, fetch, and exact remote-SHA verification.
- Exact next action — publish Checkpoint 1.5, consume the read-only Linux result,
  attest the remote SHA, then begin Checkpoint 2.1 market/consensus integration.
