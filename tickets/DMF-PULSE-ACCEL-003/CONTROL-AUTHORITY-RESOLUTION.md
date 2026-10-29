# Canonical refresh-control authority

Independent review identified that file-only production quota/consumption custody
would conflict with accepted ADR-DATA-002, not merely await source permission.

- Authority: `specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt`,
  lines 490-497, ADR-DATA-002, ACCEPTED 2026-07-18.
- Document SHA-256:
  `7ed484961cf81af1716db6daa51e6fa05ce2584c33bb04c1d59698e3bf934d72`.
- Authority manifest SHA-256:
  `b780a757b922ab8fc70388de2651860f88908a96c5d91cc87bbabbdf555700ac`.

Resolution: preserve local append-only JSON solely for owned synthetic testing;
production grants require canonical PostgreSQL control custody, atomic budgets,
one-shot consumption and cross-process claims. Add this backend under the existing
engineering authorization. Do not create an architecture exception or interpret
later provider permission as one. Production enrollment remains empty.

Only bounded authorization-control facts may be retained: hashed account/purpose
identity, approved scope/reservation identity, timestamps, counters and integrity
bindings. No provider payload, player/manager observation, credential, forecast,
scenario, transformed feature, training data or source body belongs in this store.
Source acquisition, account entitlement, control-metadata permission and the exact
reviewed pilot still require their separate approvals.

The independent grant-window finding and its original attack receipts remain
retained. Temporal scope must be recomputed from the trusted approval at both
reservation and child admission; a resealed caller grant cannot widen it.
