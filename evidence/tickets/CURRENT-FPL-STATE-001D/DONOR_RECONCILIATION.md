# CURRENT-FPL-STATE-001D donor reconciliation

Historical donor commit: `d4cc759d4600489c21ba738cfc9b357cc380554e`.

Historical file: `src/dmf_pulse/ingestion/session1.py`.

Ported concepts:

- FPL, Odds, and exact identity composition;
- one common information cutoff;
- decision-information readiness derived from source availability;
- exact source semantic/provenance hashes;
- private transient downstream source state.

Superseded:

- GW1 literal behavior and Session-1 naming;
- `PRESEASON_DECISION_SUPPORT` / donor non-production labels;
- `Session1ReviewTemplate` and its digest;
- the legacy FPL semantic helper;
- whole-provider-event count equality assumptions;
- old mapping APIs and database/persistence-adjacent orchestration;
- absence of current manager state.

New in 001D:

- accepted 001C manager state and its human-attested verification class;
- independent manager reconstruction against ACTIVE rules and the exact FULL_SEASON capability;
- accepted FPL catalogue-view binding;
- accepted 001B observed-participant team-authority invariant and extra-event collision handling;
- independent Odds market semantic and acquisition-provenance bindings;
- conservative composite rights while FPL/Odds source automated-access rights remain distinct;
- arbitrary positive Gameweek support, explicitly proven at GW2.

The donor was inspected only with `git show`; it was not merged, rebased, cherry-picked, or used
as source authority.
