# LIVE-ODDS-001 independent-review remediation plan

Status: `ENGINEERING_REMEDIATED_PENDING_INDEPENDENT_RE_REVIEW` / remediation
engineering complete; independent re-review and human acceptance remain separate.

## Immutable boundary

- Reviewed checkpoint: `6c36e73adef21b52ed54d23733e5a34c71547a6d`.
- Immutable architectural parent and fetched `origin/main`:
  `baed47bce7a158d91afe38351a2c65be60444adf`.
- Existing branch and fetched remote head:
  `integration/post-gw1/LIVE-ODDS-001-production-live-odds` at the reviewed
  checkpoint.
- The five reported implementation commits form one linear ancestry path; no
  rebase, merge, force push, replacement branch, or main mutation is allowed.

## Authority resolution

The authority manifest routes the work through A5 and A6. DMFP-17 and
ADR-ASSUR-002 prohibit raw production secrets in environment variables and
select systemd credential files. DMFP-03 models provider update/observation
time as quote semantics while DMFP-05 separates local request, receipt,
usable, and source-snapshot acquisition provenance. DMFP-06 makes freshness
and timestamp validity material to usable market observations. Therefore the
corrected market-semantic hash will retain provider-published event/market
timestamps but exclude local acquisition identity and timing.

## Checkpoints

1. **R1 — reproduce and freeze.** Record all five independent findings,
   scanner path anomaly, and property-level RED tests. Commit and push without
   production remediation.
2. **R2 — security and credentials.** Isolate unsafe raw scopes so their
   frames cannot escape, redact secret-like values before structured
   validation, remove the raw environment-secret fallback, and close related
   production scanner hits.
3. **R3 — transport deadline.** Reapply the live remaining deadline at every
   controlled blocking primitive, including response headers and underlying
   body reads, and preserve typed phase failures/retry accounting.
4. **R4 — semantic hash and downstream boundary.** Remove acquisition-only
   fields from the supported-market hash, complete the hash matrix, and run an
   actual persistence/normalisation boundary regression for additive markets.
5. **R5 — assurance and seal.** Resolve all scanner findings, correct the
   historical false evidence without deleting it, run focused/broad/static/
   build/wheel gates, record unavailable database/POSIX checks truthfully,
   perform hostile self-review, commit, push, and verify remote equality.

All five engineering checkpoints are complete. The exact R5 sealing commit is
reported in the handoff because a commit cannot contain its own object ID.

No independent or human acceptance is asserted by this plan.
