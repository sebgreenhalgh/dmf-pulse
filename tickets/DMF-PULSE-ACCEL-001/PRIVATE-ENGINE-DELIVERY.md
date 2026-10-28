# Private engine: deadline enforcement and decision evidence

Programme parent: e8efdd2c1051f75accdb2bd1f635ca02ed410241.
Integrated release parent: ea3f12bb7ca435331cd3be5b68986e777f68bd54.
Branch: readiness/DMF-PULSE-ACCEL-001-release.

## C: actionable lifetime

Previously, `dmf pulse` and manual `private-v1 live-transient` could complete
computation after the official target Gameweek deadline and still return a
recommendation. Information-cutoff checks protected the model's inputs, but did
not establish whether an operator could still act on the output.

Both services now check the authenticated official deadline before solving,
after rendering and receipt sealing, and at the public CLI publication boundary.
Equality with the deadline is expired. Missing, naive, invalid, reversed or
exception-raising clocks fail with sanitized typed errors. No arbitrary execution
buffer is introduced. Computation after the information cutoff remains valid
before the official deadline; this does not admit later source evidence.

An in-memory frozen actionability receipt binds the exact decision and report.
A separate required transient `publication_not_before` timestamp carries the
service's last observed time into the CLI, including the post-sealing sample.
It must be aware, no earlier than the receipt check, and before the deadline.
Publication samples the clock after binding validation and rejects rollback
below that high-water mark. The timestamp grants no authority and creates no
retention permission. Existing synthetic `run` and historical `replay` remain
independent of today's clock.

These checks precede output; they do not claim an atomic OS clock-and-terminal
write or that a human will complete an FPL action before expiry. The report shows
its official expiry. No FPL account write or new provider request is performed.

## D: existing one-Gameweek evidence becomes visible

The actual pulse one-Gameweek report now includes a deterministic section derived
from the validated decision: information cutoff, Stage-7 minutes confidence and
family, historical/stale player-prior status and cutoff, explicit position
fallback players, Stage-9 Monte Carlo status and reasons, scenario count and
decision hash. Historical GW1 acceptance is explicitly scoped; current carry
forward does not inherit it. The Grade-E limitation remains visible.

No confidence score, probability, player value or model parameter is invented.
The three-Gameweek report keeps its existing scoped evidence; a one-Gameweek
confidence is not advertised as confidence in the entire horizon. Reports remain
transient and no new HTML, database, telemetry or cache store is introduced.

## Numerical comparison and verification

The accepted market `code_identity()` hashes every installed Python source file.
Adding modules necessarily changes real-build lineage and downstream seals.
Independent comparison retained the initially unequal decision hashes and traced
all changes to provenance seals and embedded screen-SHA disclosure text. Legal
actions, tactics, points distributions, paired comparisons, future state and
joint-scenario numerical content are compared exactly.

A separate clearly labelled TEST-ONLY experiment pins both market code-identity
lookups to the recorded D2 identity and requires both original complete decision
hashes. Production identity authentication is unchanged. Evidence records initial,
diagnostic and final captures separately, including their source-byte bindings.
Single synthetic timings are not speed benchmarks or football-accuracy evidence.

New negative tests exercise before-solver, during-solver, rendering, sealing and
CLI expiry, exact deadline, invalid clocks and cross-boundary rollback. Real
synthetic one-/three-Gameweek stack tests and inherited tiny optimiser oracles
cover numerical and legal behaviour. The external installed-wheel check exercises
the public pulse publication boundary using a synthetic in-memory service result;
it does not claim a live-provider run. Full-stack execution is verified separately.

Independent review preserved and remediated clock sampling before validation,
missing evidence-time lower bounds, missing sanitization, overbroad confidence
wording and the post-sealing rollback gap. Logs retain test-fixture mistakes and
the repository-manifest newline defect instead of recasting them as infrastructure.

## Remaining production constraints

This is branch-integrated operational hardening and reporting, not activation.
The decision service still discloses bounded incoming/action candidates, three
Gameweeks, zero terminal value, constant prices, no simulated future information,
NO_CHIP_EXPLICIT and POINTS_MODE_ONLY. Current player allocation needs stronger
lawful longitudinal calibration. Team-strength research remains shadow only.
Human acceptance, mainline integration and production activation remain separate.
Final exact-SHA CI and publication bindings are in the external release receipt.
