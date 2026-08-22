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

## Secondary complete-diff scope check

After Owner Scope Amendment 1 was prepared in the preserved local governance
commit, complete base-to-local-HEAD ticket scope validation found exactly one
further unmatched path:

`src/dmf_pulse/assurance/secret_scan.py`

That path contains the REV-005 remediation which makes scanner exclusions
relative to the requested repository root. The correction prevents an
absolute parent named `review_pack`, `.venv`, or another excluded component
from suppressing the repository scan. It was already independently re-reviewed
at `b7b7022d99a2b56ac485c9f810c11926b64b25cd`, where REV-005 was closed.

The remaining problem was governance-only: the exact assurance source path
was absent from LIVE-ODDS-001's original allowed areas. No scanner change was
made after the independent re-review.

## Owner Scope Amendment 2

The human owner subsequently authorized LIVE-ODDS-001 to include exactly the
existing independently reviewed change at:

`src/dmf_pulse/assurance/secret_scan.py`

This amendment grants no assurance wildcard, scanner redesign, other source
path, new test, configuration change, dependency change, or wider product
scope. It is not authority to modify the reviewed scanner implementation.

## Resolution sequence

1. LIVE-ODDS-001 originally allowed only its declared paths.
2. Implementation and sealing refreshed the PRC-013 active manifest.
3. Independent re-review identified the missing authority as `NEW-001`.
4. The human owner subsequently issued Owner Scope Amendment 1.
5. The ticket and this evidence now record the exact additional path.
6. Secondary complete-diff validation found the independently reviewed
   REV-005 scanner path outside the original allowed areas.
7. The human owner issued Owner Scope Amendment 2 for that exact existing
   source path.
8. The LIVE-ODDS-001 and PRC-013 current manifests are regenerated under both
   explicit amendments using canonical repository tooling.

## Boundary confirmation

- Resolution: Owner Scope Amendment 1
- New exact cross-ticket path: `evidence/tickets/PRC-013/current_manifest.json`
- Secondary resolution: Owner Scope Amendment 2
- New exact assurance source path: `src/dmf_pulse/assurance/secret_scan.py`
- Broader scope granted: **NO**
- New source code added during governance continuation: **NO**
- Scanner changed after independent re-review: **NO**
- Broader assurance authority: **NO**
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
  `7737e7a0e85a587b8d21a37c4677e4bf3a48e5ba91cc0805ac561a791b21cf2d`.
- `uv run python scripts/generate_repository_manifest.py --ticket PRC-013`:
  1,135 files; active-manifest SHA-256
  `4f5541d27d784604eddc4bcd499db081c5bc7775b6f9a312c57f80ba30fb645a`.
- Canonical validation of both `RepositoryManifest` values against the current
  repository deliverables: **PASS**, zero drift errors.
- Exact ticket-scope assertion: **PASS**; the PRC-013 authorization occurs
  exactly once, the scanner authorization occurs exactly once, and neither
  exceptional path is covered by a wildcard.
- `uv run python scripts/validate_repository.py`: **PASS**, zero errors.
- `uv run python scripts/scan_secrets.py`: **PASS**, zero findings.
- `git diff --check`: **PASS**.

PostgreSQL and native POSIX checks were not rerun because this governance-only
delta changes no product, test, or configuration file.
