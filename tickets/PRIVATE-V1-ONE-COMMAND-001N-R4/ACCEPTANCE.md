# R4 acceptance

Root counts remain bounded by the existing private candidate policy. The automatic private
continuation limit is min(available FTs at that state, existing search cap, compiled transfer
cap, available players). Explicit rules-bounded contracts retain paid-transfer semantics.
The current shortlist is reused unchanged. Optional scope metadata is sealed in search/request
hashes; its absence preserves existing serialized contracts.

The exact root sufficient family already retains the expected-optimal continuation for every
root action. Select the actual one-GW action from that complete family, independently validate
its plan, and fail closed if absent or incomplete. The report must disclose the actual-action
basis, counterfactual horizon value and exact points-minus-hits-plus-terminal decomposition.

Run new scope/counterfactual tests; Stage-11 unit/property/contract/golden tests; private rolling,
R1/R2/R3 and one-GW/frontier compatibility tests; branch coverage; Ruff; strict mypy; frozen
sync; build/installed wheel; repository/authority manifests; secret scan; diff check; and full
exact-SHA CI. Regenerate the active repository manifest before publication. Live retry is
optional only after full CI success and when runtime inputs are already present.
