# LIVE-ODDS-001 same-agent pre-review hardening

This is an adversarial same-agent review of the complete immutable-parent ticket diff. It is not an
independent review or human acceptance.

## Independent-review remediation self-review

The complete diffs from both `baed47bce` and reviewed checkpoint `6c36e73`
were inspected after focused and broad acceptance.

| Severity | Found in final pass | Closed | Remaining |
|---|---:|---:|---:|
| P0 | 0 | 0 | 0 |
| P1 | 0 | 0 | 0 |
| Material P2 | 1 | 1 | 0 |

The material P2 was an obsolete production constant naming the removed raw
environment source. It had no lookup behavior, but retaining it made the
credential-source boundary needlessly ambiguous. R5 removed it; the negative
source assertion, credential matrix, strict typing, and exact secret scan pass.

Hostile remediation checks found:

- No credential or provider canary reachable through escaping production
  traceback/cause/context locals, including nested dictionaries and slots.
- `OddsHttpRequest` contains no credential; both stdlib transport failures and
  the client/parser boundary raise only after unsafe frames return normally.
- Only the non-secret systemd credential directory identifier may come from
  the environment. No raw API-key environment fallback, CLI source, or `.env`
  source remains.
- TLS hostname/certificate verification, approved host/path, redirect block,
  bounded body, quota, rights, cutoff, and no-fallback transport selection are
  unchanged.
- Deadline tests prove enforcement at TCP, TLS, write, headers, every raw body
  receive, retry delay, and the second attempt. The synchronous OS resolver
  limitation is disclosed rather than hidden behind a worker or fallback.
- The semantic hash payload contains no acquisition/provenance-only key;
  provider timestamps remain semantic under the recorded authority decision.
- Additive market data reaches neither production persistence preparation nor
  the actual consensus/fair-price input. Mandatory H2H remains fail closed.
- Root-relative scanner coverage works beneath `review_pack`; zero findings is
  genuine and no remediation allowlist entry was added.
- No dependency, migration, identity, Stage-6 algorithm, orchestration, PR,
  merge, tag, main mutation, provider call, real credential read, or database
  write was introduced.

The four PostgreSQL cases, canonical database-backed wheel verifier, native
POSIX run, and direct Windows console shim are truthfully environment-blocked
or unavailable as recorded in `KNOWN_LIMITATIONS.md`. The isolated installed
wheel import and exact Python console entry point passed. No unsupported gate
is represented as PASS.

## Historical implementation findings and closure

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
