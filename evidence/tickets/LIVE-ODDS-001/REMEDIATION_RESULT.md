# LIVE-ODDS-001 remediation result

Status: **ENGINEERING_REMEDIATED_PENDING_INDEPENDENT_RE_REVIEW**.

This result closes independent-review findings REV-001 through REV-005 on the
existing branch. It does not assert independent acceptance, human acceptance,
merge, tag, or production activation.

## Git boundary

- Immutable parent: `baed47bce7a158d91afe38351a2c65be60444adf`.
- Reviewed checkpoint: `6c36e73adef21b52ed54d23733e5a34c71547a6d`.
- Branch: `integration/post-gw1/LIVE-ODDS-001-production-live-odds`.
- R1: `7e660ca44f4844d88d74db6e4334fad2b14a82f2`.
- R2: `ac638e3ee6bbce8064a06e96102c2cfaa00be0d5`.
- R3: `a9f325763ae17d08f03c47cbd9bde3d5a2228182`.
- R4: `5475348b77b0be3fbd8766f4565721b98819d652`.
- R5: the sealing commit containing this result; its exact local and remote
  SHA are verified and reported in the external handoff after commit/push.

## Finding closure

- **REV-001 CLOSED.** The transport uses one monotonic attempt boundary and
  applies the shorter live phase/total bound before each TCP address connect,
  TLS handshake, request write, header wait, and raw receive. The deadline
  reader sits beneath `HTTPResponse` buffering, so one outer body read cannot
  hide multiple stale-timeout waits. Retry delay and prior attempts reduce the
  next attempt's total/read/connect budgets. TD-01..12 and added write/TCP/TLS
  properties pass.
- **REV-002 CLOSED.** Unsafe credential/raw parser, client, and transport
  helpers catch every ordinary lower-level exception and return sanitized DTO
  state. Public raising frames have released the raw inputs. Request metadata
  stores no credential. SEC-TB-01..19 recursively inspect traceback, cause,
  context, production locals, mappings, sequences, dictionaries, and slots;
  no canary is reachable.
- **REV-003 CLOSED.** Production credential resolution permits only the
  systemd credential file identified by `CREDENTIALS_DIRECTORY`. No raw
  API-key environment-value fallback or production identifier for one remains.
- **REV-004 CLOSED.** The market semantic payload includes provider/contract
  domain identity; provider event identity, participants, commence time;
  bookmaker identity; supported H2H/totals line/outcome/price material; and
  provider-published update timestamps. It excludes snapshot/body/request
  identity, request/receipt/capture/cutoff/usable times, age at receipt, quota,
  rights, quality warnings, and other acquisition provenance. HASH-01..12 pass.
- **REV-005 CLOSED.** Scanner exclusions are root-relative. Both production
  signals and every synthetic source signal were resolved without adding an
  allowlist entry. The exact scanner genuinely covers the mandated worktree
  and returns exit 0, `PASS`, zero findings. The historical false assertion is
  retained and corrected in `EVIDENCE_CORRECTION.md`.

## Provider drift and downstream boundary

Valid H2H/totals plus a harmless additive provider family remains usable with
deterministic warning metadata. Additive material is absent from accepted
semantics. The production `OddsPersistence.prepare()` boundary followed by the
actual consensus evaluator produced exactly two canonical H2H books and six
H2H observations; no unsupported or totals observation/fair-price material
entered the current Stage-6 market consensus.

Mandatory H2H missingness/duplication/incompleteness, invalid prices or lines,
invalid provider timestamps, post-cutoff material, secret-like provider fields,
rights denial, and quota contradictions remain fail closed. Optional totals
degradation remains explicit and never zero-filled.

## Acceptance summary

- Frozen sync: 40 packages checked.
- Ruff: 642 files formatted; repository lint passed.
- mypy: 247 source files passed strict typing.
- Unit: 2,031 passed, 452 deselected.
- Property: 88 passed, 23 deselected.
- Contract: 72 passed, 68 deselected.
- Non-PostgreSQL security: 51 passed, 10 deselected.
- Dependency-relevant Odds/markets: 430 passed, 4 PostgreSQL cases deselected.
- Remediation coverage matrix: 291 passed, 4 PostgreSQL cases deselected;
  aggregate 94.53% branch-aware coverage.
- Final focused sealing matrix: 163 passed.
- Module coverage: scanner 97%, client 90%, credentials 95%, current 95%,
  parser 99%.
- Repository validation: exit 0, `PASS`, error count 0. The ticket and active
  repository manifests each bind 1,135 files; the LIVE-ODDS-001 manifest
  SHA-256 is
  `48b830ba9c2c9aff27f663e6b0567a4fb6f560ac8b7b6c62b6dea3e87bf80045`.
- Final wheel: `dmf_pulse-0.2.0-py3-none-any.whl`, 841,021 bytes,
  SHA-256 `16eba3453b937118be5ebbaa944228f03210b097d071433627c8223f6cc1b44e`.
- Isolated offline wheel import and Python-invoked console entry point outside
  the source tree passed with `dmf 0.2.0`; request metadata had no credential,
  raw environment secret input resolved to no credential, packaged markets
  were `h2h,totals`, cost was 2, and the default transport was
  `stdlib_http_client`.
- Exact secret scanner: exit 0, `PASS`, finding count 0.

Exact commands are recorded in `COMMAND_LEDGER.txt` and branch-aware detail is
retained in `coverage.json`.

## Environment boundaries

`DMF_TEST_DATABASE_URL` was absent. The four PostgreSQL retention/quota tests
and canonical database-backed wheel verifier are **ENVIRONMENT_BLOCKED**, not
passed. No database was provisioned. The host was Windows, so native POSIX
evidence is unavailable. Windows application control blocked direct execution
of the generated `dmf.exe` shim; invoking the installed wheel's exact console
entry point through its isolated Python interpreter passed with exit 0.

No provider request, real credential read, database write, dependency change,
migration, PR, merge, force push, tag, or acceptance action occurred.
