# GW1 2026/27 Readiness — Session 1 Live Input Foundation

## Immutable context

- Original immutable GW1 parent — `9eb57143f6ee92f67c78607cc386678d962e62d4`
- Canonical working branch — `readiness/GW1-2026-27-live-input-initial-squad`
- Publication-reconciliation starting branch head — `d75a172018f932693c4d51dc3d803819075c3cac`
- Checkpoint 1.1 implementation commit — `448749c072900642a922ae1456d0d30111a3e9ea`
- Checkpoint 1.2 capability commit — `d8e95a442d24d0547a2b7a5fb585da94f66dcfe4`
- Checkpoint 1.2 evidence commit — `36a5c755330d5d7eeb465cbfa0e21b70cc0bf777`
- Publication workflow run — `32182179765`

## Checkpoint status

| Checkpoint | Status | Durable evidence |
|---|---|---|
| 1.0 Remote state / progress bootstrap | COMPLETE | Immutable-parent ancestry and recovery-bundle continuity verified. |
| 1.1 Runtime odds credential foundation | COMPLETE | Existing accepted implementation preserved unchanged. |
| 1.2 Current official FPL input foundation | COMPLETE | Capability commit above provides the governed manual/transient current-input contract, service, CLI, operator documentation and tests. |
| 1.3 Live The Odds API input foundation | INCOMPLETE | Not started in this reconciliation. |
| 1.4 FPL / odds identity integrity | INCOMPLETE | Not started. |
| 1.5 Session-1 artifacts / operator workflow | INCOMPLETE | Not started. |

## Publication reconciliation

- The previously claimed Checkpoint 1.2 capability and evidence commits were not present on the canonical branch, temporary branches or retained recovery bundle.
- Commit `2a06f154c6ac7f0edef314daea534b916c0a4dad` contained only a malformed compressed publication payload; it never produced a valid capability commit.
- The minimum missing Checkpoint 1.2 implementation was reconstructed from the accepted branch architecture, retained partial operator documentation and the frozen Checkpoint 1.2 requirements.
- Publication is a normal fast-forward continuation from `d75a172018f932693c4d51dc3d803819075c3cac`; Checkpoint 1.1 ancestry is preserved and no force update is used.

## Checkpoint 1.2 capability

- Governed current official-FPL inputs: players and element IDs, teams, positions, current prices, official status/availability fields, fixtures, Gameweek/event identity, GW1 deadline and bootstrap game settings.
- Provenance and temporal fields: source paths and hashes, `captured_at`, `received_at`, `information_cutoff`, official deadline, `usable_at`, configuration hashes and rights decisions.
- Canonical identity boundary: exact season-scoped provider identities with deterministic canonical lookup digests; cross-provider mapping remains out of scope.
- Data-quality controls: duplicate/missing/unknown identity checks, target-Gameweek and deadline consistency, team/position references, positive prices, fixture scheduling, schema-drift warnings and fail-closed malformed-input handling.
- Rights status: manual import, transient processing and private internal use are allowed; automated access and raw storage are denied; unresolved derived storage is denied fail-closed.
- Runtime effects: no network request, database open, raw write or derived write occurs; the operator remains responsible for deleting manually captured source files after validation.

## Temporal-integrity status

- Timezone-aware timestamps are mandatory.
- `captured_at <= received_at <= information_cutoff <= official GW1 deadline` is enforced.
- `usable_at` is the validation receipt time and cannot exceed the cutoff.
- Post-cutoff availability evidence is rejected, target fixtures must kick off after the official deadline, and the paired bootstrap/fixtures capture shares one operator-declared capture time.
- The official resources expose no independent provider publication timestamp; this is recorded as unavailable rather than fabricated.

## Validation

- Focused current-input tests — `36 passed`.
- Wider affected FPL regression — `196 passed, 6 deselected`; the deselected tests require PostgreSQL and the capability intentionally opens no database.
- Ruff format — PASS.
- Ruff lint — PASS.
- Strict mypy on affected production modules — PASS.
- CLI synthetic current-input smoke — PASS, including redaction and no-transport/no-persistence assertions.
- First-party repository secret scan — executed after evidence attestation.

## Known limitations

- A real operator-captured 2026/27 official payload was not supplied to this workflow; the production manual capture remains an operator checkpoint.
- Automated official-FPL retrieval remains denied by the current rights profile.
- No raw or derived persistence, cross-provider identity mapping, odds retrieval, projections, optimisation, squad recommendation, captaincy, prospective logging, PR, merge or production activation is included.

## Restart handoff

- Exact next action: **CHECKPOINT 1.3 — LIVE THE ODDS API INPUT FOUNDATION**.
