# RUL-002 CLI Contract

All commands use the existing `dmf` app, stable exit codes and `--json` output. JSON is sorted/deterministic and contains no absolute private path unless explicitly requested for operator diagnostics.

## Commands

`dmf rules validate SOURCE_DIR [--json]`
- success 0 for valid complete or explicitly valid incomplete draft;
- report status, production eligibility, files, source hashes, unknown/conflicted blockers and warnings.

`dmf rules compile SOURCE_DIR --output FILE [--json]`
- compile valid source to canonical JSON;
- refuse overwrite of an existing different artifact unless a distinct explicit version/output is used;
- output ID/version/hash/status.

`dmf rules hash COMPILED_FILE [--json]`
- revalidate canonical content and return its self-consistent hash.

`dmf rules show RULESET [--json]`
- show metadata and concise rule summary, not source comments.

`dmf rules diff LEFT RIGHT [--json]`
- typed added/removed/changed rule paths with verification/source changes;
- stable ordering; exit 0 even when differences exist; invalid input is nonzero.

`dmf rules score-fixture RULESET SCENARIO [--json]`
- exact fixture output; refuses ruleset/scenario mismatch or unknown required scoring rule.

`dmf rules score-gameweek RULESET SCENARIO [--json]`
- exact fixture and aggregate output.

`dmf rules activate RULESET --approval APPROVAL [--registry DIRECTORY] [--json]`
- only VERIFIED, production-eligible, source-complete rules can activate;
- partial 2026/27 target returns nonzero stable error `RULESET_ACTIVATION_BLOCKED` and blocker details without guessing.

## Exit convention

- 0 success;
- 2 invalid CLI usage;
- 3 validation/schema/input failure;
- 4 activation/governance block;
- 5 output collision/integrity failure;
- 1 unexpected safe internal failure.

Equivalent repository-wide error conventions may be used if already established, but document and test the exact mapping.
