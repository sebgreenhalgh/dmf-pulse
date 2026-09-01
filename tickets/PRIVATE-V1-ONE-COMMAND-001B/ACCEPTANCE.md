# PRIVATE-V1-ONE-COMMAND-001B engineering acceptance

`DirectUrllibTransport` must preserve the complete response body when CPython has closed or
detached the underlying socket after consuming all declared bytes but before the sentinel EOF
read. The response reader remains authoritative: a genuine body-read error still fails closed,
and a timeout-adjustment error on an open socket is never swallowed.

The hotfix preserves HTTPS-only, the fixed official-FPL host/path grammar, GET-only requests,
redirect rejection, TLS validation, connect/read/total timeouts, the response byte ceiling,
bounded retries and request budgets, zero retention, and secret-safe errors. It does not alter
Odds acquisition, authenticated-team policy, one-command orchestration, provider rights, or any
model/scorer/optimiser behavior.

Acceptance requires focused and affected regressions, branch coverage and static gates; real
Windows/Python 3.13 bootstrap and fixtures reads through `DirectFplClient`; installed-wheel,
repository and secret checks; a pushed isolated branch; and exact-final-SHA CI success. The real
entry ID and any credentials remain runtime-only. No PR, merge, tag, writeback, persistence or
production activation is authorised.
