# D1 offline diagnostic contract

Parent `5ca798db9f2d75c8b577e8b37e9ee21205a2d0f0`; authority scopes A3/A8/B1,
ADR-DATA-004/005/006, ADR-EVAL-001/004/006 and ADR-ASSUR-006. This subordinate
ticket implements the explicit D1 request. No provider access or A03 authority.

The parent `StrengthEvidenceError(ValueError)` is caught by the runner's
`(ValueError, OSError)` handler. A four-string whitelist discards all other typed
causes. D1 replaces classification by exception text with enums and narrow typed
boundaries; arbitrary exception messages/tracebacks never enter safe output.

Historical A02 stays UNKNOWN_HISTORICAL / P01_OUTCOME_ADMISSION_FAILED_CLOSED /
NOT_RETAINED. Never infer a cause from elapsed time or fabricate missing receipts.
All original P01/A01/A02 files are authenticated read-only. The consumed A02
context is denied independently of artifact-root location or marker deletion.
Default/live HTTP transport is disabled; only explicit fake transport/connection
injection exercises the completed diagnostic implementation. No reset/force flag.

Closed strict models admit only finite stages/reasons/route/content-type classes,
aware UTC times, bounded aggregate counters, status codes, observed byte lengths
and SHA256 digests with explicit completeness/JSON-validation state. No body,
scores, IDs, names, arbitrary headers/messages, exception text or tracebacks.
Stopped records are sealed and stored exclusively/content-addressably. Failure
receipts are minimal private internal provenance/evaluation evidence within the
unchanged qualified rights profile31261d9304c20a178d730e57e7d06c82423b68a816bac73d517887d58b3caaf2;
no raw storage, public display or redistribution permission is broadened.

Success selection, result typing, identity mapping, projection ordering,
validators, persistence-before-D2 and all numerical scoring remain unchanged.
Synthetic parent-envelope equality, all49metrics/30rows and original OpenFootball
path regression are required. All test transports are fake and sockets denied.

Allowed changes: D1 diagnostic module, existing P01 ingestion/acquisition and
runner diagnostics, narrow packaging/wheel verification, D1 tests/ticket/evidence,
PLANS, required manifests and workflow verification call. No numerical evaluator,
rules, model, source/rights config, dependency or activation changes.

Fresh independent verdict CLEAR_FOR_P01_A03_REAUTHORIZATION_DECISION permits only
a later human decision; it grants no execution authority. Resolve all P0/P1 and
material P2 before publication. Run literal acceptance commands, publish only the
requested branch, and require exact-SHA CI success. No PR/merge/tag.
