# OPR-002 — post-GW10 failure recovery

Active authority is the owner's 2026-11-02 consolidated recovery request, the
accepted OPR001 standing scope, and the unchanged A12-ops-assurance/B6-control-UI
authority manifest. OPS-001/002/003/004/006, GOV-004, DATA-003/004/007 and
SRC-001/004 apply. The contract grants no new source or execution authority.

Baseline: af1c22396a2ed147267ef22ae6baba39ab35f7cb. Original actual audit SHA256:
1936458c207f98373965c8a7845efb52ba2c5d49912eb94e43a07901921b36d5.
GW10 remains consumed. Its reservation, original ledger identity and all prior
consumption markers are immutable; no reset, refund, replacement or re-enrollment.

Implement safe diagnostic contracts in operation/ and reviewed compatibility
glue (dashboard/current.py, current_sources.py, runtime.py, views.py, app.py,
current_failures.py and CLI/UI as necessary). Preserve source route limits,
mathematics, rules, numerical artifacts, model selection and the protected
package hash. Provider transports may be observed through existing guarded
interfaces; no provider source-body retention or new ingestion authority.

Diagnostics distinguish named stages, recognized versus unrecognized typed
failures, unexpected exceptions, admissions, started transports and completed
responses. Record only allowlisted code-owned values, authenticated route
identities, bounded timestamps/status categories and counts. Never serialize
exception text, input/context, credentials, cookies, headers or provider bodies.
Diagnostic events cannot grant permission, replay requests or replace a ledger.

Investigate integrity refusals with owned Windows trees and fault injection.
Preserve original receipts and all original checks. No watcher reset/rearm,
accept-changed path or signed-root replacement is permitted. A historical cause
is asserted only with evidence; an offline defect is reported separately.

Regression includes realistic owned 2026/27 response shapes, manager identity,
history selection, profile binding, Stage 8/9/12 calculation, safe error
translation, timeouts, malformed/missing data, expired authorization and failed
completion. Source sockets are denied in engineering tests. Synthetic output
is explicitly owned engineering evidence, never real live acceptance.

Run targeted tests, then literal lint/format/type/coverage/build/frozen-sync/
installed-CLI/repository-validation/secret-scan gates and changed-source CI.
Independent review must clear material findings. Deliver a capped review pack.

Release only through the accepted signed compatibility mechanism: same owner,
key, ledger, material policy, numerical identity, dependency/platform pins and
source permissions. Routine technical correction requires independent review,
not another personal acceptance. Any material conflict stops installation.

The next real acquisition is permitted only for a new officially eligible
Gameweek through ordinary dmf start, with fresh automatic credential/quota
checks, at most one paid EPL GET, two reserved credits and zero retries.
Engineering readiness is not successful live recommendation acceptance.
