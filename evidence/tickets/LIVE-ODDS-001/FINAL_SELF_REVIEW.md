# LIVE-ODDS-001 same-agent pre-review hardening

This is an adversarial same-agent review of the complete immutable-parent ticket diff. It is not an
independent review or human acceptance.

## Findings and closure

| Severity | Found | Closed | Result |
|---|---:|---:|---|
| P0 | 0 | 0 | No credential disclosure, rights escalation, host escape, cutoff bypass, or consensus contamination found. |
| P1 | 1 | 1 | Unexpected secret-like provider extras were blocked but their values could exist briefly in a parsed Pydantic model. Parser-boundary value redaction and repr/serialization regressions now close this path while preserving the field-name blocker and raw body hash. |
| Material P2 | 1 | 1 | `OddsHttpResponse` claimed immutability while exposing a mutable header dictionary. The view is now a mapping proxy and mutation is directly rejected by test. |

## Hostile checks completed

- Credential sentinel absent from request target/fingerprint/repr, response/result repr, lower
  exception cause/context, redirect location, provider body/header handling, request-ID evidence,
  logs, dataclass conversion attempts, parsed Pydantic serialization, and committed evidence.
- TLS verification remains enabled; host/path/method/query are exact; redirects are never followed;
  no `UrllibOddsTransport` fallback call exists.
- Reads stop at maximum plus one byte; connect/read/total failures and retry attempt counts are
  typed; quota cost and response-header evidence remain enforced.
- Supported H2H/totals alone enter the current semantic hash. Additive market ordering is
  canonical, warning/drift metadata is explicit, and source body hashes still distinguish payloads.
- Mandatory H2H corruption, secret-like extras, provider timestamps after receipt, non-prematch and
  post-cutoff events, invalid quota provenance, and required-rights denial all remain fail closed.
- Later-main mapping, persistence, retry, raw-retention, publication, and service lifecycle code was
  retained; readiness live orchestration and identity code was not substituted.
- Built wheel contains the new current/credential/client/parser modules and the updated provider
  resource. An isolated offline install imported from site-packages, reported `dmf 0.2.0`, loaded
  `h2h,totals` with cost 2, and selected `stdlib_http_client`.

No unresolved P0, P1, or material in-scope P2 remains. Environment and scope limitations are
recorded separately in `KNOWN_LIMITATIONS.md`.
