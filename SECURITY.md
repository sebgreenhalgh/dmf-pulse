# Security policy

DMF Pulse is a private repository. Do not open a public issue containing a vulnerability, private identifier, raw provider payload, credential, token, DSN, cookie, or machine serial. Report concerns privately to the repository owner using the private GitHub security/reporting channel available to collaborators.

## Foundation controls

- No production secret belongs in Git, configuration, command lines, environment snapshots, evidence, exceptions, tests, or CI artifacts.
- Configuration accepts reference identifiers only; FND-001 performs no implicit secret resolution.
- Runtime and tests make no network or database calls.
- First-party scanning is deterministic and fails closed for suspected credentials/private keys; narrow allowlisting requires a path, rule, rationale, and non-secret fingerprint.
- Dependencies are limited by the active ticket and locked by uv. A new dependency requires purpose, licence/maintenance/security review, lock refresh, and evidence.
- Generated review packs must be scanned and validated before sharing.

If a real secret is observed, stop work, prevent further disclosure, rotate/revoke it outside this repository, preserve sanitized incident evidence, and notify the owner privately.
