# Exact automatic credential seam

REQUEST004 sections5.1/5.3 require native Windows credentials in the actual
accepted Odds path. `src/dmf_pulse/ingestion/odds/transient.py` changes from
Wave003 SHA256 `3d457edf7c94e822f9589e838a1939a359341283eb2fd018359dee25e16eee50`
to `3faeb93796f3989a92ea58a63da64269161d64d4e490ca2d08f1a8e3aa472a81`.

The default provider becomes the lazy automatic credential provider, retaining
Linux systemd and an explicit session environment selector. The injected provider
contract is structural. Quota exhaustion still refuses first. Exact source
automated/transient rights now check before creating the client, and actual secret
resolution remains in the existing client's authorized request boundary. The old
environment-value presence probe is removed. No source route, market mapping,
bookmaker aggregation, horizon, scoring, solver or projection changes.

Keep both historical full-file digest maps and authorize only these exact new
bytes. Every other R8B frozen file remains bound to its existing digest. Independent
credential code review inspected the new seam and exercised denied lookup; the
full one-/three-GW comparison and exact-SHA CI remain additional release gates.
