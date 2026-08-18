# Secret scan

First-party deterministic repository scan: **PASS**, zero unallowlisted findings.

The initial scan correctly surfaced a lexical false positive for the public domain supersession
enum assignment. The serialized/API term is retained, and its exact path/rule/fingerprint is
narrowly allowlisted in `.secret-scan-allowlist.json` with a rationale.
No wildcard or raw secret is allowlisted. No credentials were read, stored or printed.
