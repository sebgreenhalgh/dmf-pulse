# OPT-010 reference fixtures

This directory contains the governed, test-only inputs for the OPT-010 TEST/REPLAY CLI and
installed-wheel acceptance path:

- `reference_ruleset_source/` is the authored schema-1.1 source. Its provenance is limited to
  the frozen OPT-010 test contract and the cited DMFP-02 reference sections.
- `reference_ruleset_test_only.json` is the normal canonical compiler output. It has ruleset
  identity `opt010-test-synthetic`, lifecycle `REFERENCE_ONLY`,
  `production_eligible: false`, and canonical ruleset hash
  `adb24ef11bae13a131dd27434ad87e43a1a0dbbff95ba5f70c89aafbe6ebe188`.
- `request.json`, `stage9_gameweek_result.json`, and its `.sha256` sidecar form the static
  optimiser input set bound to that exact ruleset hash.

The fixture expresses only the manager-tactics values already frozen by OPT-010. It is not a
copy or promotion of the 2026/27 `CAPTURED_UNVERIFIED` artifact, makes no target-season
verification claim, and has no authority for production scoring or activation.
