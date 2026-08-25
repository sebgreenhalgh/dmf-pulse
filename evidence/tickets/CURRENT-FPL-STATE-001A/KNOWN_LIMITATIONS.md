# CURRENT-FPL-STATE-001A known limitations

- The compiler supports only the explicit current ingestion season `2026/27` and competition
  `PL`. It does not infer season metadata from official payloads, which do not carry an accepted
  authoritative season declaration for this boundary.
- Input acquisition remains a human operational step under the approved rights profile. No live
  provider reachability, current payload contents, or operator workflow was exercised; acceptance
  uses synthetic repository fixtures and temporary derivatives only.
- Source deletion remains the operator's responsibility. The compiler performs no filesystem
  deletion and cannot truthfully issue a deletion receipt; the safe summary and runbook require
  immediate deletion after success or failure.
- The complete bundle is intentionally private and transient. No persistence or subsequent
  process boundary is supplied, and the safe CLI output is not a reconstructable player catalogue.
- Windows Application Control blocks the generated `pytest` console launcher in this local
  environment. The exact same frozen interpreter executed the suite through
  `uv run python -m pytest` (76 focused and 273 inherited tests passed); GitHub Actions must prove
  the canonical launcher on the final Linux SHA. No failed assertion was hidden by this boundary.
- Official target-event flags are accepted only when the requested event is explicitly unfinished,
  explicitly not previous, and has the exact explicit current-or-next tuple. Non-target optional
  flags may remain absent, but contradictory true flags on any event fail closed. Historical/future
  planning outside that published state is not supported.
- The local-file boundary protects against pre-existing symlinks, descriptor substitution to a
  different filesystem object during validation/open, and post-open pathname replacement detected
  by stdlib identity checks. Bytes come from the validated descriptor. This does not claim absolute
  protection against an attacker controlling the kernel or filesystem implementation.
- Canonical FPL-to-Odds identity, manager-owned state, availability/minutes modelling, projections,
  optimisation, and orchestration remain separate future tickets.

Independent review, human acceptance, PR creation, merge, and production activation remain
pending and are not claimed.
