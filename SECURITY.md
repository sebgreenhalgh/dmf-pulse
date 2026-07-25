# Security policy

DMF Pulse is a private repository. Do not open a public issue containing a vulnerability, private identifier, raw provider payload, credential, token, DSN, cookie, or machine serial. Report concerns privately to the repository owner using the private GitHub security/reporting channel available to collaborators.

## Foundation controls

- No production secret belongs in Git, configuration, command lines, environment snapshots, evidence, exceptions, tests, or CI artifacts.
- Configuration accepts reference identifiers only; FND-001 performs no implicit secret resolution.
- Runtime imports make no network or database calls. DAT-003 tests may connect only to the disposable local PostgreSQL 18.4 service through the explicit TEST-only boundary.
- First-party scanning is deterministic and fails closed for suspected credentials/private keys; narrow allowlisting requires a path, rule, rationale, and non-secret fingerprint.
- Dependencies are limited by the active ticket and locked by uv. A new dependency requires purpose, licence/maintenance/security review, lock refresh, and evidence.
- Generated review packs must be scanned and validated before sharing.
- Committed configuration stores only secret references. The disposable database uses the visibly fake `changeme` test credential; URLs, doctor output, exceptions, and evidence must not expose credentials or query secrets.
- Raw observations and source snapshots are immutable at the database layer. Corrections create new temporal versions and retain prior provenance.

## FPL-004 provider-data controls

- Deterministic development, tests, CI, acceptance, evidence, and review artifacts use only the approved synthetic fixtures. They must never make a live FPL/provider request or retain a real provider payload.
- Every provider operation is authorized against an immutable Rights Profile before access, raw write, derived promotion, bundle publication, backup, export, training, or display. `UNKNOWN` is enforced as deny.
- The supplied official profile permits bounded transient manual validation only. It denies automated access and persistent raw/derived storage; transient bytes are bounded and removed in a guaranteed cleanup path after both success and failure.
- The snapshot command must return `RIGHTS_BLOCKED` before constructing or invoking transport under the official profile. A successful HTTP response cannot confer rights.
- Import/replay paths are bounded to approved local roots and reject traversal or symlink escape. Payload decoding rejects excessive bytes/depth, duplicate JSON keys, malformed UTF-8/JSON, and unsafe types.
- Logs, exceptions, CLI output, PostgreSQL rows, evidence, and review archives must omit payload bodies, credentials, cookies, query values, credential-bearing URLs, private manager data, and local secret/temp paths.
- Database URL command options accept reference identifiers only. Literal credential-bearing URLs are rejected and sanitized before error reporting.
- Every retrieval remains an immutable envelope with append-only processing events. Database constraints enforce monotonic lifecycle/terminal behavior and canonical season/competition coherence.

If a real secret is observed, stop work, prevent further disclosure, rotate/revoke it outside this repository, preserve sanitized incident evidence, and notify the owner privately.
