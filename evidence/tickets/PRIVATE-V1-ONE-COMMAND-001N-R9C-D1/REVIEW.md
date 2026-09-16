# R9C-D1 hostile review

## Local hostile review

The only runtime source change is the dedicated shadow probe. Its fixed blocked model
uses a strict frozen schema with extra fields forbidden and no details/error/exception
field. All known boundaries return a finite reason/stage pair without inspecting an
exception. The code has no `str(exc)`, `repr(exc)`, traceback, exception logger,
exception print, `exc.args` or `vars(exc)` pattern.

Sentinel chained exceptions containing token, entry, player-name, Windows-path, URL
and JSON-body strings are injected at every post-acquisition boundary. Tests capture
returned data, JSON, stdout, stderr and logging and find none of those strings.
They also assert a fake six-request acquisition failure retains six, invokes acquisition
once, reports no retry, no persistence, no training, no Odds and no Stage 7--11 call.

The prior blocked live attempt is not replayed or reinterpreted. R9C-D1 only permits
a future separately authorized attempt to identify its safe failing stage.

Independent review and publication remain pending.

## Independent-review remediation

The first fresh read-only review raised one valid P2 acceptance gap: acquisition
failure was injected with a generic chained exception but not the repository's typed
`IngestionError` required by the ticket. The test now models one acquisition attempt,
increments the synthetic direct-client count from zero to six, raises a secret-bearing
`IngestionError`, and asserts the closed `FPL_ACQUISITION_FAILED` /
`ACQUIRE_FPL_SNAPSHOT` payload retains only the count. It also adds explicit prohibited
recommendation and Odds-service sentinels to the successful synthetic probe. No runtime
source change was made for this remediation. A re-review of the amended candidate is
required before publication.

## Fresh independent read-only review

Exact reviewed candidate before this evidence-only recording amendment:
`904d01a0e3036bb34b4d38152c8d28ce1d43409b`.

The reviewer verified the typed acquisition remediation advances the synthetic client
from zero to six requests and raises `IngestionError`; the result remains exactly
`FPL_ACQUISITION_FAILED` at `ACQUIRE_FPL_SNAPSHOT` with no leaked detail. It also
verified the explicit recommendation/Odds sentinels and found no runtime-source change
in the remediation. The review found no P0, P1, P2 or P3 issue.

Verdict: `CLEAR_FOR_PUSH_AND_EXACT_SHA_CI`.
