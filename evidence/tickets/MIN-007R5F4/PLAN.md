# MIN-007R5F4 final-output truthfulness and lookup plan

1. Reconstruct canonical final payload identity from authoritative run/model/dataset
   values, frozen role marginals/scenarios, and persisted final rows.
2. Harden migration `20260807_0006` so every direct `DRAFT -> COMPLETE` transition
   validates player payloads, positions, row-derived hashes, team result, and the
   combined output identity.
3. Require complete core state in exact prediction lookup and preserve existing
   complete/as-of behavior.
4. Add focused truthfulness and draft-visibility regressions, then run the literal
   23-command acceptance contract and record exact evidence.

No provider, live network, credentials, model changes, CLI changes, new migration,
or MIN-007H scope is permitted.
