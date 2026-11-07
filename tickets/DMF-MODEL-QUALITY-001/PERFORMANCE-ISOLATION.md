# Cold-adapter benchmark isolation

Resume source `a6ae92e6e05951e72a4b817b9fa1e66b66861641` and failed CI run
42341835872 attempts 1 and 2. Preserve both failures and all earlier evidence.
The accepted benchmark authority is
`tickets/CURRENT-TEAM-STRENGTH-001A/ACCEPTANCE.md:55`: module-only performance
selection, no timing instrumentation, thirty cold artifact calls under 100 ms.
Canonical CI still selects all repository performance tests.

Run this one benchmark in a fresh pytest child using the current interpreter,
repository, configuration, home/network isolation and exact original test body.
The parent remains selected by the unchanged repository-wide performance command.
The child clears the same artifact-validation cache immediately before timing;
the complete first artifact authentication, all thirty calls and unique-output
assertion remain inside the original contract. Assert zero initial cache state,
one miss and 29 hits afterward. Keep the literal wall-clock limit `< 0.1`.
No model, source, fixture, dependency, policy, workflow, GC setting or timer change.

The parent must reject nonzero exit, startup failure, a 90-second supervision
timeout, absent/malformed/oversized JUnit, zero/multiple/wrong cases, any failure
or skip, missing/duplicate/incorrect proof properties and invalid elapsed time.
Retain raw child streams, JUnit and their hashes. Emit that bounded evidence to
the normal CI log, including proof of 30 outputs, 30 unique digests and cold-cache
state. Do not count a supervisor exit alone as completed benchmark work.

This isolates the benchmark from unrelated pytest collection and earlier tests.
It does not claim a proven explanation for the hosted 413.5/491.2 ms failures.
The earlier GC traces and Python patch comparison did not explain those failures.
Linux diagnostics match CPython 3.13.18 but retain OS/library/hardware differences;
instrumented profiles are not acceptance. Fresh exact-SHA FULL CI must demonstrate
the candidate correction. No additional unchanged-source retry is authorized here.

Validate supervisor negative controls alongside the actual native Windows parent/
child and complete repository-wide performance selection. Preserve fixture and
package hashes, execute the continuation's applicable local gates, independently
review, commit/push and require all twenty exact-SHA CI jobs. Production activation,
provider calls, archive deletion and real research qualification remain separate.
