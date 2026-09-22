# D1 independent review

Reviewer: fresh read-only `/root/d1_independent_review`, separately from the
implementation and the earlier read-only control-audit agent. No provider,
credential, private snapshot or live authorization access occurred in review.

## Findings and remediations

1. The earlier control audit confirmed the input/derived work-budget defect and
   supplied the real 12-versus-13-candidate witness. Human clarification expressly
   permits corrected control/container hashes while preserving decisions,
   projections and classifications. The reviewer confirms the corrected split.
2. Intermediate review required preserving `continuation_mode`; unlike the root
   transfer limit, this scope field is a hard input. It remains explicitly hashed
   and a negative regression proves mode changes cause control divergence.
3. Material P2: premature INPUT_INVALID could mislabel an unexpected projector
   exception. Remediated by unknown pending state and classification only in the
   existing input handler. Reviewer independently ran all six new tests: PASS.
4. Final disclosure hardening: validate exact diagnostic type/raw fields before
   serialization; turn validation exceptions into fixed safe text. This prevents
   serializer warnings and direct-helper validation errors exposing forged
   private values. Independent tamper/consumed-authority verification passed.

No unresolved P0/P1/material P2 finding remains in the reviewed production diff.
Independent executions: 63 initial diagnostic/control tests; five additional
tamper/serialization/consumed-authority tests; six pending-projection tests.
These subsets complement, not replace, the implementation's full acceptance.

## Review answers

| Question | Reviewed result |
| --- | --- |
| Successful semantics | Requests, solve mathematics, projections, thresholds and classifications unchanged; only human-authorized control/container identity differs. Exact-parent five-case execution evidence still required below. |
| Major failure localization | Closed stages cover world, Stage-8, post-solve bindings/controls, movement, fixture, materiality, sealing and timing. |
| Disclosure safety | No arbitrary message/class parsing; strict enums/fields, safe serialization, suppressed chains and finite fallback. |
| World distinction | Separate started/completed flags and failed-world identity. |
| Stage-8 distinction | Pending, caught input failure, true BLOCKED and successful/prior-fallback projection are distinguished from reconciliation. |
| CRN | Tests random-input seed/namespace/scenario/draw/weight identity, not transformed scores or points. |
| Candidate screen | Derived search limits may differ; input controls remain equal and confounded classification remains available. |
| Providers | Zero live FPL/Odds/OpenFootball requests; synthetic/public retained inputs only. |
| Consumed approval | Old L1 authority rejected before credential/provider access. |
| Future live gate | Separate fresh human decision/ticket required; no new approval or activation created. |

## Verdict

Provisional clear code review; exact final verdict pending completion of the
running real five-case parent-equivalence/L1/A2/ordinary regression population.
No clearance for live execution or production is implied.
