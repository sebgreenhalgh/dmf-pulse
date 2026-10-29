# ACCEL-003 exact transient seam historical-freeze exception

Checkpoint CI run [40944800918](https://github.com/sebgreenhalgh/dmf-pulse/actions/runs/40944800918),
shard 9 job 123697896415, failed the older R8B byte-freeze assertion in
`tests/unit/ingestion/test_horizon_rights_approval.py:186`. The other 274 tests in
that shard passed. The source-midpoint receipt and original UTF-16 failure log
remain in root ignored `review_pack/ci-source-midpoint.json` and
`review_pack/ci-job-123697896415.log`. This remediation changes tests and this
receipt only; it does not modify or relax product source, rights or acquisition.

The retained ACCEL-003 `REQUEST.txt` SHA256 is
`98da8cf3c9b9c38696e4ff8bbf63a9d00faadfa97c2eb2088f819d69af6ddbb2`.
Section 5.4 requires reuse of the accepted FPL/Odds/OpenFootball clients with one
coherent information set; section 6.2 authorizes engineering of a narrow, inactive
operator-refresh rights/usage proposal with exact account, request and credit
budgets. The frozen `CONTRACT.md` explicitly permits narrow injection seams in
existing source clients while protecting numerical kernels, active profiles,
historical artifacts and default model policy. None of these texts authorizes
provider access or an active approval. The exact new source seam was reviewed
within CP2; this exception records its whole-file identity explicitly.

The complete historical `_R8B_UNMODIFIED_EXECUTABLE_HASHES` map is preserved,
including the old `ingestion/odds/transient.py` SHA256
`6dc8e6195b84491697caf7530b194fbc5d164982c9a20377d63eca0608ebb49e`.
One separate reviewed exception admits only that exact relative path with whole
file SHA256
`3d457edf7c94e822f9589e838a1939a359341283eb2fd018359dee25e16eee50`.
Every other R8B provider/A2 executable digest remains exact; the original FPL
registry byte check remains unchanged. The test name now discloses that this
single reviewed seam can differ from its historical parent. There is no wildcard,
suffix exception, normalized-code comparison or broad compatibility allowlist.

Before patching, repository searches covered the old/current transient digest,
transient-path references, unmodified-source maps and parent-identical guards.
The only historical hash guard naming this seam is the R8B map above. The R8A
guard continues to freeze Odds parser/client bytes, and the L2 model/provider
boundary guard does not name this seam. Neither is changed.

The reviewed seam adds optional injected `rights_profile`, `quota`,
`maximum_attempts=1` and `require_known_quota` parameters. Defaults preserve the
existing profile loader, client constructor without retry override and fetch
without supplied quota. Explicit injection may narrow authorization/retry/quota
behavior; it does not replace the existing Odds client, parser or current-input
builder. Compatibility evidence is concrete:

- `test_operator_odds_transient.py::test_legacy_defaults_preserve_exact_existing_client_and_fetch_arguments`
  checks the exact legacy profile, constructor kwargs and fetch kwargs using an
  owned fake client; no retry override or quota argument is supplied by default.
- `test_one_command_odds_transient.py::test_transient_service_invokes_existing_client_parser_and_current_builder`
  retains the real parser/current-builder path and exact temporal/zero-retention
  assertions; missing credentials still block before client construction.
- The existing operator-seam tests enforce rights/quota rejection before
  credential/client access, exact injected single-attempt/quota forwarding and
  rejection of any expanded retry policy.
- The unchanged R8A parser/client byte guard and R8B remaining executable/registry
  assertions protect the surrounding accepted boundaries independently.

All checks use owned fixtures/injected clients; there are no provider requests,
real credentials, active-profile edits or product-code changes in this patch.

Author validation: 118 focused R8B/R8A, default-wrapper and injected-operator tests
passed in 3.29 seconds; Ruff format/check and whitespace checks passed. Independent
comparison of the authenticated historical and reviewed current classes passed
five cases (happy path, missing credential, malformed JSON, naive cutoff and empty
range), with exact model JSON and credential/profile/client/fetch call order and
kwargs equality. That separate receipt is root ignored
`review_pack/accel003-independent-legacy-default-equivalence.json`, SHA256
`ca3fc107d3571bb37190d408bfef0c15b1484e51b867df01ba3237efe2773d42`.
