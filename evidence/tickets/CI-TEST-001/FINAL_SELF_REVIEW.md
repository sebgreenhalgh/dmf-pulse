# CI-TEST-001 final self-review

## Historical adversarial checks

- The negative payload is valid JSON: yes.
- `CandidateSquad(player_ids=("p00",))` validates before the canonical comparison: yes.
- The explicit bytes are identical on Windows and POSIX: yes; `write_bytes` is used.
- Canonical bytes for the same valid candidate load successfully: yes.
- The explicit noncanonical bytes raise `OptimisationError`: yes.
- Malformed JSON remains a separate rejection control: yes.
- Valid JSON with an invalid model is a separate rejection control: yes.
- Detached hash and collision controls remain in the passing target: yes.
- Target and full module passed on Windows and Linux Python 3.13: yes.

## Rebuild checks

- Corrected Layer-A base file differed from the original pre-B base: no.
- Reviewed executable blob and rebuilt executable blob are identical: yes.
- Reviewed stable patch ID and rebuilt stable patch ID are identical: yes.
- Production source, workflow, coverage configuration, dependencies, config, and migrations are
  unchanged from corrected Layer A: yes.
- DIAG-02, CI-GOV, CI-FPL, LIVE-ODDS, and PR #16 are untouched: yes.

## Findings

- P0: 0
- P1: 0
- Material in-scope P2: 0

Independent lineage confirmation and human acceptance remain pending. This self-review does not
authorize a merge.
