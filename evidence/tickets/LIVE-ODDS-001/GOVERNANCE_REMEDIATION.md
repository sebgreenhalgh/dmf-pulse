# LIVE-ODDS-001 governance remediation

## Finding

- Finding: `NEW-001`
- Severity: P2, material pre-merge
- Independently reviewed HEAD:
  `b7b7022d99a2b56ac485c9f810c11926b64b25cd`
- Root cause: canonical repository assurance refreshed
  `evidence/tickets/PRC-013/current_manifest.json`, but that cross-ticket
  active-manifest path was outside the original LIVE-ODDS-001 ticket
  allowlist.

`NEW-001` was a valid governance finding. This record does not describe the
original mutation as already authorized and does not rewrite its history.

## Owner Scope Amendment 1

After the independent remediation re-review, the human owner explicitly
authorized LIVE-ODDS-001 to modify exactly:

`evidence/tickets/PRC-013/current_manifest.json`

The authorization is mechanical and governance/evidence-only. It permits the
mutable active repository snapshot required by canonical repository assurance.
It grants no wildcard, no other PRC-013 path, no product scope expansion, and
no authority to alter PRC-013 narrative, result evidence, implementation, or
historical claims.

## Resolution sequence

1. LIVE-ODDS-001 originally allowed only its declared paths.
2. Implementation and sealing refreshed the PRC-013 active manifest.
3. Independent re-review identified the missing authority as `NEW-001`.
4. The human owner subsequently issued Owner Scope Amendment 1.
5. The ticket and this evidence now record the exact additional path.
6. The LIVE-ODDS-001 and PRC-013 current manifests are regenerated under that
   explicit authority using canonical repository tooling.

## Boundary confirmation

- Resolution: Owner Scope Amendment 1
- New exact cross-ticket path: `evidence/tickets/PRC-013/current_manifest.json`
- Broader scope granted: **NO**
- Product code changed: **NO**
- Tests changed: **NO**
- Provider configuration changed: **NO**
- Provider behavior changed: **NO**
- Security, transport, and semantic-hash behavior changed: **NO**
- Human acceptance performed: **NO**
- Next state:
  `ENGINEERING_REMEDIATED_PENDING_INDEPENDENT_GOVERNANCE_CONFIRMATION`

## Canonical reseal and validation

- `uv run python scripts/generate_repository_manifest.py --ticket LIVE-ODDS-001`:
  1,135 files; manifest SHA-256
  `b32a50a830a3c4a44a105cc49be89abfb2a8b1c16835d42f49fc1e3c0f580ce5`.
- `uv run python scripts/generate_repository_manifest.py --ticket PRC-013`:
  1,135 files; active-manifest SHA-256
  `8d3027010517e8930555869f41e4fc7e22740b012b981c936449665511ef7d43`.
- Canonical validation of both `RepositoryManifest` values against the current
  repository deliverables: **PASS**, zero drift errors.
- Exact ticket-scope assertion: **PASS**; the PRC-013 authorization occurs
  exactly once and no other PRC-013 path is allowed.
- `uv run python scripts/validate_repository.py`: **PASS**, zero errors.
- `uv run python scripts/scan_secrets.py`: **PASS**, zero findings.
- `git diff --check`: **PASS**.

PostgreSQL and native POSIX checks were not rerun because this governance-only
delta changes no product, test, or configuration file.
