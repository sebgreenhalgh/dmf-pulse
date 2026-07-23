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

If a real secret is observed, stop work, prevent further disclosure, rotate/revoke it outside this repository, preserve sanitized incident evidence, and notify the owner privately.
