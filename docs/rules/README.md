# Rules foundation operations

The source contract is 13 named YAML files. The loader accepts only a bounded safe subset and the compiler creates one canonical JSON artifact with semantic source hashes, source-bundle hash, compiler version, lifecycle state, blockers, and a self-hash that excludes only `ruleset_hash`.

Public lifecycle:

- `REFERENCE_ONLY`: compile and score research/synthetic scenarios; never publish target decisions.
- `CAPTURED_UNVERIFIED`: validate, compile, show, and diff; unresolved required fields block scoring and all activation.
- `VERIFIED`: complete and production-eligible but not active; activation additionally needs an exact approval record.
- `ACTIVE`: immutable publication at one ID/version/path. Any overwrite is an integrity collision.

Fixture scenarios contain explicit aggregate event facts and eligible/on-pitch goals conceded. Clean sheets are derived from minutes, position, score eligibility, and dismissal continuation. BPS and points values come from the compiled rules. Zero-minute Gameweek placeholders receive zero BPS/bonus and are excluded from competition ranking.

The checked 2026/27 claims are metadata-only deltas. The listed unknown families are intentional governance blockers, not TODO values.
