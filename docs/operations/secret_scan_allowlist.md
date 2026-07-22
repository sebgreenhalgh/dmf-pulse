# Secret-scan allowlist

The default is an empty `.secret-scan-allowlist.json`. A false positive may be allowed only after inspecting the source and proving the matched value is non-secret.

Each entry must contain one exact repository-relative `path`, exact `rule_id`, lowercase SHA-256 `fingerprint` emitted by the scanner, and a non-empty `rationale`. Wildcards, directory entries, raw matched values, rule-only suppression, and path-only suppression are rejected. The scanner never prints the matched value.

Prefer changing a test fixture to construct a fake credential at runtime over allowlisting a credential-shaped literal in Git.

Oversized, unreadable, non-UTF-8, and symbolic-link files fail the scan closed. The only binary
exception is the exact bundled `Europe/London` TZif asset, and its reviewed SHA-256 is enforced in
code; generated `.coverage` and review/build/cache directories are operational exclusions.
