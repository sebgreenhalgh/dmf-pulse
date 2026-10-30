CP2 completes private enrollment preparation, deterministic wheel assembly and
reviewed default launch using the existing installed registry and authorizer.
No real enrollment, account qualification, owner acceptance or installation is
claimed. The public installed registry remains empty.

Editable private pilot input is accepted by `operation prepare-pilot --input`.
Its output remains NOT_GRANTED. A complete package and three separately reviewed
source qualifications can be checked against a clean base wheel with
`operation prepare-enrollment`. This authenticates RECORD, exact base bytes,
manager/routes, deadline, quota/account closure, fixed one-shot limits and the
actual wheel implementation fingerprint. The result remains NOT_GRANTED.

After supplier/account/owner decisions exist, the maintainer prepares a private
carrier REVIEW ZIP using `scripts/prepare_private_release_carrier.py`. This
packages the separately accepted exact ReleasePermit record into a carrier
wheel, plus a detached receipt. It does not authenticate the supplied decision,
install the carrier or change runtime authority. Independent release review and
the owner's deliberate installation of the exact reviewed carrier are the trust
transition, just as for executable code. No application source is hand-edited.
There is no application command that accepts caller JSON as an enrollment.

Only after that separate trusted installation can `operation assemble-wheel`
resolve the permit from the fixed installed resource. It transforms only that
resource and RECORD, preserving the implementation. It checks all pinned
identities, expiry and canonical filename, and never overwrites an output.
Detached review binds the resulting full wheel SHA. Install that exact reviewed
private wheel using the ordinary package installer; run `operation launch` to
start the installed default manager/deadline scope without typing hashes.
Pairing and Refresh remain manual; launching does not fetch provider data.

Permission expiry and withdrawal are checked during reservation, acquisition,
credential lookup, native FPL send and publication. Source qualifications cannot
borrow a different profile's permission. Current quota observations supplied by
the operator retain their own provenance and unknown used/last-cost fields;
actual response headers remain a separate accepted contract.

The existing control-only prepare/init/recover commands remain canonical. A
reviewed control receipt and separately permitted control-metadata retention are
required; creating a new ledger cannot reset previous spend.

CP2-TARGETED: 288 passed. Independent source/wheel review: 35 tests and 30 owned
cases, zero unresolved P0/P1/material P2 in scope. CP6 full installed/native/DB,
numerical parity and exact-final-SHA CI are separate outstanding release gates.
