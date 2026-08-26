# CURRENT-FPL-STATE-001B implementation result

Status: **IMPLEMENTED PENDING INDEPENDENT REVIEW**.

The implementation starts at immutable parent
`ee16489054ff78c59eb67897e5e9e52f785ccd6e` on branch
`integration/current-fpl/CURRENT-FPL-STATE-001B-fpl-odds-identity`. Donor concepts were reconciled
manually; donor history was not merged.

## Implemented capability

- Additive typed contracts represent explicit current team aliases, explicit target-fixture
  bindings, bound resolution requests, resolved teams and fixtures, complete coverage, and the
  final private `FplOddsIdentityMap`. Historical `OddsMappingPlan` behavior remains unchanged.
- `current_fpl_identity_view_sha256` independently binds the accepted 001A semantic digest and the
  exact current teams, target event/deadline, target fixtures, relevant identities, source semantic
  hashes, common cutoff, and source usability time consumed by 001B.
- Odds event identity is deterministic over provider, sport, provider event ID, participants,
  commence time, and common cutoff. It excludes prices, bookmaker order, outcome order, and other
  identity-irrelevant market material. Full accepted Odds provenance is hashed separately.
- Team resolution accepts exact strings present in an approved transient plan only. It rejects
  stale official names, unknown identities, context or rights drift, duplicate provider strings,
  many-to-one aliases, test authority, post-cutoff approval, and any bound source/plan substitution.
- Fixture resolution uses only explicit target provider-event bindings and target FPL fixtures
  selected by exact event identity. It requires exact home/away orientation, exact UTC kickoff,
  fresh approval, complete one-to-one coverage, and target kickoff after the official deadline.
- Provider responses may contain unrelated later events. An unbound event is ignored only when it
  cannot be an exact target-fixture candidate; an exact duplicate candidate is `AMBIGUOUS`.
- The bridge is immutable, self-validating, private, transient in memory, database-free, and
  non-persistent. It preserves the accepted FPL effective derived-storage denial and requires
  accepted LIVE-ODDS transient/private rights with no retained raw payload.

## Verification checkpoint

- Ticket-focused team and fixture suite: 61 passed.
- Branch-aware ticket-owned identity/mapping suite: 115 passed; 90.06147540983606% aggregate
  coverage, with 705/756 statements and 174/220 branches covered. The warnings in this combined
  coverage population are inherited Pydantic Decimal serializer warnings from synthetic Odds
  model-copy fixtures; the focused ticket run is warning-free.
- Inherited non-database population: 427 passed. Four database-prerequisite setup errors in the
  initial unsplit selection were rerun under the required disposable PostgreSQL environment.
- PostgreSQL 18.4 population: canonical migrations through `20260807_0006`; 92 passed after the
  required `DMF_ENVIRONMENT=TEST` and test database URL were supplied.
- Frozen sync, repository-wide format/lint, strict typing through the frozen interpreter, build,
  generic/ODD-005/GCS-008 installed-wheel gates, repository validation, and secret scan passed on
  the final evidence-bound tree. The installed-wheel checks used clean environments outside the
  repository and the ODD-005 gate observed zero network requests.

No provider request, credential read, current real mapping capture, persistent current-state write,
PR, merge, independent review, human acceptance, or activation occurred.
