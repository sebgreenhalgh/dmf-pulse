# PRIVATE-V1-ONE-COMMAND-001I implementation summary

`CurrentPenaltyHierarchy` is now a strict v2 transient contract. Its canonical raw positive rows
allow sparse ranks and duplicate team ranks, while a separately sealed full-catalogue team record
derives usability deterministically. Missing rows remain explicit as `NO_PUBLISHED_ORDER` rather
than causing whole-payload rejection. Duplicate rows remain present and hash-bound even though
they are unusable for selection.

The private Stage-9 adapter filters hierarchy rows by the team usability record. Exact sparse
ranks pass unchanged for usable teams; all rows for ambiguous teams are omitted. No tie-break or
renumbering was added. The existing 001H exhaustion-policy selection is unchanged, so the shared
scored/extra penalty resolver still prefers usable current order, then positive governed
historical role share, then the explicitly opted-in private positive goal-share proxy. Derived
ambiguity/unavailability warnings flow through the existing private limitation set into decisions
and reports.

`HumanCliProgress` is a run-local observer passed through the existing application-service layer.
The normal human CLI constructs it with a STDERR writer; `--no-progress` supplies a no-op observer.
All emitted content is fixed stage text or safe counts/timings. Monotonic clocks prevent negative
durations. Daemon heartbeat threads are scoped to blocking contexts, joined on success, typed
failure, or Ctrl+C. No progress value enters execution identity, result contracts, persistence or
the final report, and no numerical/optimisation implementation changed.
