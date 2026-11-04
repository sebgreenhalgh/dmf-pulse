# OPR-004 ? persistent Seb's Desk and private local analytical warehouse

Active owner instruction: REQUEST.txt (SHA256 5ff9d85d71d057ec0d2de30934f5f5c2fccee78eadd7ac2d1d569821c16d91b5).
Baseline: 0e3c0fadcf5f84d0527327423c7979463baaabf9.
Authority: manifest scopes A12-ops-assurance, A3-data-foundation, B6-control-UI;
DMFP-20 ADR-OPS-001/004/006, DATA-003/004/005/007, UI-001/002/003/004/007.
The new explicit launch/refresh instruction supersedes the earlier OPR-001
launch-acquisition coupling, without changing its material acquisition policy.

Implement persistent loopback browser history, explicit credential-gated Refresh,
transactional SQLite derived read model and read-only analysis/export commands.
PostgreSQL remains the sole authority for admission, consumption and publication.
No source routes, budgets, numerical engines, models, rules or dependency change.
No live provider acquisition to test consumed GW10. Preserve every canonical row,
marker, original result and P01 artifact. Use owned fixtures for refresh tests.

Rights: existing StandingPolicy.private_derived_forecast_retention_approved=True;
raw_source_retention=DENIED_TRANSIENT_ONLY. Permission provenance stays
OWNER_ATTESTED_NOT_ISSUER_AUTHENTICATED. Persist only typed derived presentation,
decision, provenance and closed diagnostics; never raw input/scenario sources,
restricted market bodies, credentials or an executable research replay dataset.
Historical decision.replay_retention describes its original execution rights;
new retention is specifically a private derived analytical read model.
No external upload, public service, content creation or account write.

Immutable pending snapshot precedes canonical publication; a canonical digest
confirmation exposes it to historical readers. Recovery reconciles exact digests
idempotently; an orphan pending record is never the latest successful snapshot.
Browser APIs retain origin/session/CSRF/CSP/size protections, single-job admission,
no secret reflection and last successful view through failures or refreshes.

Acceptance: all owner section J cases using actual installed processes and owned
inputs, authenticated retained GW10 import, read-only SQL and migrations/recovery,
full engine parity, required literal release gates, independent technical review,
signed compatible installation and real browser verification. No further routine
owner acceptance is required within accepted standing maintenance boundaries.


Analytical boundary qualification: DMFP-20 bytes SHA256
7ed484961cf81af1716db6daa51e6fa05ce2584c33bb04c1d59698e3bf934d72,
ADR-DATA-002 at lines489-503 keeps PostgreSQL operational truth and Parquet
research artifacts; ADR-IMPL-002 at lines2783-2799 is PROVISIONAL and rejects
SQLite as the production baseline. This request (SHA256
5ff9d85d71d057ec0d2de30934f5f5c2fccee78eadd7ac2d1d569821c16d91b5)
explicitly adds SQLite as a separate non-authoritative private derived read model,
never a queue, ledger, provider database or replacement canonical/research format.
No existing source-format or operational authority is changed.

The legacy blanket check in scripts/validate_repository.py:806-842 prevented
this explicit narrow read model. Its exception now requires the exact request
hash and permits stdlib imports only in operation/analysis_store.py and
operation/analysis_cli.py. SQLite driver dependencies, SQLAlchemy URLs, arbitrary
modules and database artifacts in source remain prohibited. Eight adversarial
checks prove the boundary. The same validator selects the new OPR-004 scoped
manifest without modifying accepted older manifests. These necessary automation
and test files are included in this execution contract.
The exact request also has a narrow binary entry in .gitattributes so Windows
and Linux retain its authenticated bytes; authored documentation uses LF.

Historical access is explicitly separate from active acquisition permission.
require_history_policy verifies the same immutable installed policy, signature,
bytes, trust, accepted-at floor and withdrawal checks; it does not grant expired
provider access. All provider/enrollment paths keep strict require_policy.
Failed-attempt read models preserve closed diagnostics and observed quota receipts
separately from the last complete snapshot, including explicit owned provenance.
