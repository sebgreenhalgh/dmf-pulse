# CI-TEST-001 root cause

Classification: `PRE_EXISTING_MAIN_DEFECT`

The inherited negative fixture wrote the text
`{"player_ids":["p00"]}\n` and expected `load_canonical_json` to reject it.

On POSIX, those bytes are already canonical LF JSON for the valid
`CandidateSquad(player_ids=("p00",))`. The production loader therefore correctly accepted the
payload. On Windows in the historical test environment, text newline translation wrote CRLF, so
the raw bytes accidentally differed from the canonical LF encoding and the test passed.

The negative control was consequently testing platform text-newline translation, not canonical
byte enforcement. The loader's raw-byte read, JSON parse, model validation, canonical
regeneration, and bytewise comparison are correct and were not changed. `CandidateSquad`
validation and canonical JSON encoding were also not changed.

The remediation writes explicit bytes with an insignificant JSON space:
`b'{"player_ids": ["p00"]}\n'`. They are identical on Windows and POSIX, valid JSON, and valid
`CandidateSquad` input, but are intentionally different from compact canonical encoding. The test
first proves that canonical bytes for the same model load successfully, then proves that the
explicit noncanonical bytes raise `OptimisationError`.

DIAG-02, the separate evaluation CLI marker, remains unresolved and untouched. The monolithic CI
runtime limitation also remains separate and unresolved.
