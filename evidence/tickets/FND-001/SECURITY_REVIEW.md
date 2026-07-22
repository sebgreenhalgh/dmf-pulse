# FND-001 security and secret review

- First-party repository scan: **PASS, zero findings**.
- Scan coverage fails closed for oversized, unreadable, non-UTF-8, and symbolic-link files.
- The only binary exception is the hash-pinned public-domain IANA `Europe/London` TZif payload; generated `.coverage`, build/cache, and review directories are explicit operational exclusions.
- Constructed tests cover mappings, strings, URLs, query values, exception text, JWT, AWS/GitHub/OpenAI/Slack-style tokens, high-entropy values, and bare/RSA/EC/OpenSSH/encrypted/DSA private-key headers.
- Reference-only configuration rejects credential shapes before storage; display redaction applies the same shared predicate and never includes rejected values in errors.
- Doctor retains no environment values, user name, tool path, GPU name, serial, Device ID, or Product ID. It performs no network or database call.
- Allowlisting is exact path + rule + fingerprint with a mandatory rationale; the repository allowlist is empty.
