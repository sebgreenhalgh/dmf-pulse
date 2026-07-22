# DMF Pulse execution plans

## RUL-002 — governance remediation and rules foundation

- Ticket/stage: `RUL-002`, A2.
- Required branch/baseline: `stage/A2/RUL-002-rules-foundation` from `12049a7de23a4a8fcca3d219dbcab1bf5e1027ea`.
- Outcome: generic governed evidence, a strict split-YAML rules compiler and lifecycle, pure fixture/Gameweek scoring, deterministic CLI contracts, and a validated review ZIP capped at 20 root files.
- Authority: official target-season rules/provider terms; newest ACTIVE/ACCEPTED DMFP-20 decision; most-specific accepted module; DMFP-00; earlier research; implementation convenience. Ticket contracts are subordinate execution constraints.
- Constraints: offline; no new dependencies; no database/provider/model/optimiser/UI code; no activation or inferred completion of the partial 2026/27 ruleset; no push or merge.

### RUL-002 checkpoints

- [x] 2026-07-22T12:00:00Z — verified the v1.1 correction notice, all pack and fixture hashes, corrected independent oracles, exact baseline/branch/clean-tree preconditions, and the 104-test FND baseline.
- [x] 2026-07-22T14:28:55Z — RUL-002.0: generated the complete 94-entry DMFP-20 index, hash-pinned stage authority requirements, generic ticket/evidence/review contracts, and exact runtime lock graph; authority and assurance targeted tests pass.
- [x] 2026-07-22T14:28:55Z — RUL-002.1: implemented strict safe-subset YAML, exact typed authoring schemas and cross-file coherence, deterministic compilation/hash/diff, in-memory integrity revalidation, and atomic immutable lifecycle gates.
- [x] 2026-07-22T14:28:55Z — RUL-002.2: implemented pure configured scoring/BPS/competition-ranking/Gameweek aggregation; corrected v1.1 goldens plus boundary, property, lifecycle, schema, and false-success mutation probes pass with 98.84% rules branch coverage in the focused run.
- [x] 2026-07-22T15:14:18Z — RUL-002.3: exposed all rules CLI commands, updated package/docs/least-privilege CI, and passed the final precommit quality gate with 200 tests, zero skips, 90.81% overall branch coverage, 98.88% rules branch coverage, frozen-lock validation, clean-wheel verification, repository validation, and secret scanning. The exact 19-command final ledger, actual-commit evidence, and 20-file ZIP are deliberately generated from the clean committed tree into ignored evidence/review paths.

### RUL-002 decision log

- The v1.1 fixture family is immutable input. No v1.0 digest, expected output, or manifest is admissible.
- The checked 2026/27 deltas remain `CAPTURED_UNVERIFIED`; all unannounced rule families are typed blockers, so scoring/activation cannot guess.
- The reference/synthetic scorer consumes only compiled configuration and explicit aggregate scenario facts. Zero-minute Gameweek placeholders are excluded from BPS/bonus ranking.
- `payload_sha256` is the stable detached primary-payload digest. `archive_sha256` is reported only after ZIP creation and cannot be embedded as a self-hash.
- Command 19 is invoked exactly once against a write-ahead ledger; after the invocation, its measured duration replaces the provisional entry and the same assembler refreshes the final archive without rerunning the CLI command. Final archive digest/CRC evidence remains external to avoid self-reference.
- Two narrow ticket-required changes fall outside the enumerated `allowed_areas`: `src/dmf_pulse/__init__.py` is the existing canonical version source that must become `0.2.0`, and `.gitignore` must exclude regenerable RUL evidence so COMPLETE evidence can name the actual commit while the final tree remains clean. No other out-of-list path is changed.

---

# FND-001 historical execution plan

## Ticket and outcome

- Ticket: `FND-001`, Stage A0/A1 foundation milestone
- Branch: `stage/A1/FND-001-foundation`
- Owner: Sebastian Greenhalgh
- Implementation lead: Codex
- Independent reviewers: fresh read-only scope/security/test-gap review before acceptance
- Observable outcome: a governed, reproducible Python 3.13 workspace with an installed `dmf` CLI, strict configuration, diagnostics, first-party assurance tooling, CI, machine-valid evidence, and a review ZIP capped at 20 root files.

## Authority and decisions

- Precedence: accepted DMFP-20 decisions; FND-001 ticket/acceptance details; most-specific DMFP module; DMFP-00; implementation playbook/repository guidance.
- Controlling decisions: `ADR-PROD-004`, `ADR-GOV-001`, `ADR-GOV-002`, `ADR-GOV-004`, `ADR-RES-001`, `ADR-DATA-002`, `ADR-SRC-001`, `ADR-IMPL-001`, `ADR-IMPL-002` (provisional), and `ADR-IMPL-003`.
- Primary locators: DMFP-19 §7 Stage 1; DMFP-17 §§0.5, 0.8–0.9, and 4; DMFP-20 §0 and the decision blocks above; FND-001 acceptance and review-pack contracts.

## Baseline

- Captured before all other repository changes at `evidence/tickets/FND-001/baseline_manifest.json`.
- Existing Git HEAD: `44e63a9f2acf6627912f9a0b6d5173553db0895f` (empty initial commit).
- Existing non-`.git` files: zero.
- Remote owner parsed unambiguously as `sebgreenhalgh`; no remote mutation is authorised.
- Pack integrity: all 42 files listed by `PACK_MANIFEST.json` matched expected bytes and SHA-256.

## Ordered checkpoints

1. Install all 21 approved DMFP documents verbatim, install the implementation playbook, generate authority/document/decision manifests, and validate hashes/references/DMFP-04 edition.
2. Add concise governance, ticket records, schemas, security/contribution guidance, cross-platform operations documentation, and CODEOWNERS derived only from the remote.
3. Add the Python 3.13 `src/` package, Hatchling build, canonical `0.1.0` version, approved dependencies, exact uv lock, and clean-wheel verifier.
4. Implement and test strict Pydantic v2 configuration, deterministic overlays/redaction, Typer CLI, injected clock/process boundaries, and nonblocking hardware diagnostics.
5. Implement canonical JSON/hashing, typed evidence models/validation, manifest/repository validation, secret scanning, deterministic baseline diffing, and capped review-pack creation.
6. Complete unit/property/golden/integration coverage with offline/home isolation and achieve at least 90% branch coverage for `dmf_pulse`.
7. Add least-privilege Ubuntu CI plus scheduled/manual Windows smoke; mirror local uv/Python commands.
8. Run every mandatory command literally, record command/exit/duration evidence, conduct ordered read-only self-reviews, fix material findings, and generate/validate the final ZIP.

## Test map

- Package/CLI: installed version, installed module path, `py.typed`, JSON and human rendering, stable exit/error codes.
- Configuration: strict fields, required/malformed values, overlay precedence, path normalization, timezone/log/device validation, raw-secret rejection, deterministic/redacted output, no directory creation.
- Doctor/system: injected time/processes, safe write probe cleanup, timeout/truncation, GPU absence healthy, no identity/secret fields.
- Assurance: canonical hash stability, hash mismatch/missing/duplicate/stale reference/paid-DMFP-04 failures, schema failures, fake-secret shapes and allowlisting, review-pack 21-file refusal and detached-manifest hashes.
- Isolation: package imports cannot invoke network/subprocess/write/environment mutation; tests use no network or user home.

## Acceptance commands

The 13 literal commands in `03_ACCEPTANCE_CONTRACT.md` are mandatory, followed by installed-wheel `dmf --version` and `dmf doctor --json` in a fresh environment outside the repository. Every invocation will be recorded separately with command, exit code, duration, and concise result.

## Risks and safe fallback

- Local `python`/`uv` execution may require the approved absolute uv path because managed sandbox policy denied PATH-resolved executables; use the sanctioned uv installation and request only the narrow dependency/network permission if resolution fails.
- Zoneinfo data on Windows can vary; validation must use the Python 3.13 runtime’s available `zoneinfo` data and provide actionable failure output without adding an unapproved runtime dependency.
- Review ZIP output is requested both in-repository and beside the source pack; generate and validate in-repository first, then copy the final ZIP to the external requested destination without changing Git history.

## Progress

- [x] 2026-07-22T09:11:21Z — inspected Git status, remote, branches, HEAD, and empty tree.
- [x] 2026-07-22T09:11:21Z — captured deterministic empty-repository baseline as the first artifact.
- [x] 2026-07-22T09:11:21Z — read the controlling pack in the mandated order and verified all 42 pack hashes/byte counts.
- [x] 2026-07-22T09:20:00Z — Checkpoint 0 complete: installed 21 exact DMFP files plus playbook, generated three governed manifests, and passed the first-party validator with zero errors.
- [x] 2026-07-22T09:20:39Z — Checkpoint 1 complete: added governance, proprietary licensing, ticket records, Codex contracts, owner-derived CODEOWNERS, and cross-platform operational documentation; manifest validation remained green.
- [x] 2026-07-22T09:48:18Z — Checkpoint 2 complete: uv resolved 29 packages for Python 3.13.9, frozen sync passed, and the wheel verified `py.typed`, installed module provenance, version, doctor, and cleanup outside the source tree.
- [x] 2026-07-22T09:48:18Z — Checkpoint 3 complete: strict configuration, deterministic overlays/redaction, path/timezone/reference semantics, and no-create loading passed targeted unit/property tests.
- [x] 2026-07-22T10:50:31Z — Checkpoint 4 complete: deterministic CLI/doctor contracts, privacy-minimized bounded probes, missing-config blocking, safe CPU fallback, and installed default timezone validation passed.
- [x] 2026-07-22T10:50:31Z — Checkpoint 5 complete: canonical evidence/hashing, fail-closed secret scan, manifest integrity, detached primary-payload digest, atomic capped review ZIP, and negative tamper tests passed.
- [x] 2026-07-22T10:50:31Z — Checkpoint 6 complete: 103 offline tests passed with 288/318 branches covered (90.57%) and strengthened import/network/write/logging false-success traps.
- [x] 2026-07-22T10:50:31Z — Checkpoint 7 complete: least-privilege Ubuntu CI, scheduled/manual Windows smoke, exact frozen commands, cross-platform documentation, and clean-clone package verification are in place.
- [x] 2026-07-22T10:54:29Z — Checkpoint 8 complete: all 14 literal mandatory commands passed, three independent read-only reviews were resolved, machine evidence validated, and a root-only 20-file bootstrap review ZIP passed full detached hash validation before final clean-HEAD assembly.

## Decision log

- Use only ticket-sanctioned Python 3.13, uv, Hatchling, Pydantic v2, Typer, PyYAML, Ruff, mypy, pytest, Hypothesis, coverage, and build.
- Use a scheduled/manual Windows smoke workflow to conserve private-repository CI minutes.
- Install `DMFP-04_DATA_SOURCES_MARKETS_APIS_AND_LICENSING_ZERO_COST_v1.0.txt` only; the validator rejects any other DMFP-04 filename/version/hash.
- Use a detached review-manifest convention: the manifest hashes every ZIP member except itself; `SHA256SUMS` hashes all other members, including the manifest.
- Treat `pytest-cov` as the unavoidable development adapter implied by the mandatory `pytest --cov` acceptance command; it adds no runtime dependency and delegates measurement to the already sanctioned coverage.py.
- Include Hatchling in the locked development group as the sanctioned build backend so its exact resolved version and transitive build dependencies are captured in `uv.lock`.
- Pin the isolated build backend to uv-resolved Hatchling 1.31.0 and keep that exact version in the development lock, preventing build-environment drift.
- Bundle the single public-domain IANA tzdata 2025b `Europe/London` TZif payload with an enforced SHA-256 so stock Windows Python can validate the sanctioned default without an unapproved runtime dependency.
- Define `codex_result.review_pack.sha256` as the detached digest of stable primary review files 04-05 and 07-19; publish the separately validated final archive SHA-256 externally because an archive cannot contain its own digest.
- Read-only self-review found no authority/scope P0 issue and drove fixes for credential-shape leakage, CPU fallback coercion, fail-open scan coverage, PEM detection, missing-config doctor false health, Windows timezone portability, branch-metric reporting, clean-clone package provenance, evidence semantic checks, and atomic review placement.
