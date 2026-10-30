# Secure credential operation

On Windows, run `dmf credentials set-odds-key` once in an interactive console.
The hidden prompt validates locally and writes only the current user's exact
Windows Credential Manager target `dmf-pulse/credentials/v1/odds`. No provider
request occurs. `dmf credentials status` reports configuration booleans only.
Rotate explicitly with `dmf credentials set-odds-key --replace`, or delete with
`dmf credentials delete-odds-key`. There is no show command or secret argument.
If secure console input is unavailable, setup refuses the echo fallback.

Windows AUTO resolves the vault entry inside authorized acquisition. A populated
`THE_ODDS_API_KEY` does not override it. Missing, unavailable or corrupt vault
records do not fall back. To select the legacy session environment explicitly,
set the nonsecret `DMF_ODDS_CREDENTIAL_SOURCE=environment` selector in that session;
the accepted provider then reads `THE_ODDS_API_KEY`. Pulse never sets it, copies
the key to a child environment, or persists it. On Linux, AUTO and explicit
`systemd` use the accepted systemd credential provider; explicit `environment`
is the session-only compatibility alternative. There is no plaintext backend.

FPL is independent. `dmf credentials set-fpl-token --expires-at <actual-aware-time>`
stores a separate native target with mandatory actual expiry. Use `--replace`
when explicitly replacing an expired token. Native resolution rejects expiry
before decoding; transport checks it again after pacing and before each send.
There is no session extraction, renewal or invented refresh token. Oversized
tokens are rejected without truncation at WinCred's 2560-byte UTF-16LE bound.
Explicit `DMF_FPL_CREDENTIAL_SOURCE=environment` selects the existing session
`DMF_FPL_BEARER_TOKEN` provider on either platform. Expiring FPL credentials never
delete, rotate or require re-entry of the persistent Odds credential.

The Windows dependency is pinned `pywin32-ctypes==0.2.3` (BSD-3-Clause, no runtime
transitives), Windows-only. Pulse selects its reviewed ctypes WinCred facade;
unexpected backend selection refuses access. Upstream classifiers stop at
Python3.11; Python3.13 support is established by this programme's native tests,
not claimed as an upstream certification. Generic credentials use same-user
LOCAL_MACHINE persistence across logons. The mutation lock under LOCALAPPDATA
contains one nonsensitive byte, inherits profile ACLs, coordinates Pulse writes
across processes, and times out after five seconds. It does not protect against
arbitrary software running as the same user. Status necessarily copies the native
record internally but does not decode or display its value. Python reference
cleanup is best effort and does not guarantee memory erasure.

Credentials do not grant source rights. Opening the dashboard, demo operation,
passive operation status, approval preflight and denied/expired/quota-blocked
operations do not resolve them. Current refresh reserves and claims the existing
durable grant before its worker resolves credentials. `dmf pulse --entry-id <id>
--refresh-approval <installed-id>` uses that same enrolled worker and publication
checks. Arbitrary JSON, a key or an ID absent from the trusted installed registry
cannot launch acquisition. The registry remains unenrolled until owner review.

Primary integration references:

- https://pypi.org/project/pywin32-ctypes/0.2.3/
- https://github.com/enthought/pywin32-ctypes/tree/v0.2.3
- https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw
- https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew
- https://docs.python.org/3.13/library/msvcrt.html

The Odds API's accepted v4 transport requires transient wire query
authentication. Pulse's sanitized request descriptors, logs, evidence and browser
responses exclude the key; no authenticated URL is retained. This does not change
provider routes or permit a setup/quota probe. Account entitlement and remaining
credit evidence still require separate nonsecret qualification.

- https://the-odds-api.com/liveapi/guides/v4/index.html
- https://the-odds-api.com/terms-and-conditions.html
- https://the-odds-api.com/manage/faqs.html
