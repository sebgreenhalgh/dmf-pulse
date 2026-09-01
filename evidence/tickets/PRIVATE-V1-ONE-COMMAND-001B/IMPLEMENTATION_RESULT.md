# Implementation result

Status: implemented pending final exact-SHA CI and independent review.

The hotfix confines CPython socket access to one timeout-adjustment helper. If `settimeout()`
raises, the exception is ignored only when the socket's public `fileno()` proves that the
descriptor is closed/detached; the stable response `read()` interface then supplies the
authoritative EOF. Public `Content-Length` is reconciled afterward, so a clean premature EOF for
a declared body still fails as `SOURCE_UNAVAILABLE`. An open or unclassifiable socket error and
genuine read timeout, TLS and I/O failures retain their existing typed behavior.

HTTPS/GET/path allowlists, redirect rejection, TLS validation, connect/read/total timeouts,
maximum response bytes, retry/request budgets, zero retention and error redaction are unchanged.
Odds, authentication policy, automatic input assembly, models, scoring, optimisation, captaincy
and reporting are untouched.

Real Windows/Python 3.13.9 source-tree and external installed-wheel clients both completed public
bootstrap and fixtures reads. The genuine one-command retry reached the independent credential
preflight blocker `THE_ODDS_API_KEY is missing.`; no Odds defect is claimed and no credential was
requested, displayed or persisted.
