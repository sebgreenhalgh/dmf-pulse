# GW1-MKT-001 authority resolution

Status: **RESOLVED FOR IMPLEMENTATION; PENDING HUMAN ACCEPTANCE**

Recorded: 2026-08-20

## Exact authorization

The operator remediation directive at
`C:\Users\sebgr\.codex\attachments\2ca565f0-f935-4ca0-928e-dd2e0ce94c52\pasted-text.txt`
has SHA-256
`508447aaba3493e649012f7e6a5659799841301d3bb3571161b9096b7a1a946e`.
It authorizes the bounded current-GW1 market-primary path from exact base
`ed6fc1a1190fcc924e6fe0c078f18c7ae25e5a94` on branch
`readiness/GW1-2026-27-market-primary-remediation`.

## Conflict and narrow resolution

NRM-006 explicitly excludes totals and freezes its public persistence
contracts. The directive specifically requests a Stage-6/8 totals adaptation.
This ticket therefore permits only an **in-memory current-GW1** supplement:
one exact full-time 90-minute O/U 2.5 line per bookmaker, using the existing
Stage-6 Decimal normalisation policy and the existing Stage-8 constraint set.
It neither changes an NRM-006 frozen table/schema nor claims that its excluded
markets are retrospectively accepted there.

## Governing constraints retained

- The provider request contains only `regions=uk` and `markets=h2h,totals`;
  documented quota cost is exactly two credits (two markets × one region).
- H2H is mandatory. Totals absence, malformed content, line mismatch, or
  staleness produces explicit fixture-level degradation while H2H remains
  eligible.
- Only pre-match `FULL_TIME` / `FULL_TIME_90` O/U 2.5 is in scope. No props,
  team totals, correct score, exchange, live/in-play, rho/Dixon-Coles, or
  database migration is implied.
- The combined Stage-8 constraint set preserves each family result hash. It
  intentionally has no synthetic outer source hash when H2H and totals hashes
  differ.
- All official-FPL/current-provider material remains transient; no real key or
  request was used by this implementation.

## Non-authorization

This evidence does not accept a support-prior artifact, a player-allocation
artifact, a production forecast, a provider entitlement change, or a current
GW1 decision. Those require their own reviewed evidence and human acceptance.
