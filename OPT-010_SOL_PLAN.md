# OPT-010 Stage 10 reconciliation and implementation plan

Status: Gate 0 is resolved and frozen by `tickets/OPT-010/ticket.yaml` on 2026-08-15.
Implementation is `READY` for Luna on the exact branch/base below; this document remains the
detailed reconciliation contract and the ticket controls any amended final ruling.

## 1. Verified repository and proposal state

- Authoritative implementation base: `a33f46cd7ec190fbd4959e2840527116f22547ac`.
- `HEAD`, local `main`, and `origin/main` all resolved to that exact SHA.
- Current branch at inspection time: `main`.
- Initial worktree state: clean; `git status --short --branch` returned only
  `## main...origin/main`.
- The later implementation branch must be
  `stage/A10/OPT-010-one-gameweek-optimiser`, created from the exact immutable base only
  after Gate 0 is satisfied. This planning run did not create it.
- Alembic has one head: `20260807_0006 (head)`. OPT-010 needs no migration and must leave
  that head unchanged.
- The installed dependency graph has no Pyomo or HiGHS. The accepted repository uses
  Python 3.13, uv, Hatchling and the `src/` layout. OPT-010 must not change `pyproject.toml`
  or `uv.lock` unless a separately approved solver/dependency decision explicitly requires it.

The supplied ZIP has SHA-256
`b97931e2237706201d82bd13d4f1946f86c2f5bf827b3ba51c8364e5a43043f2` and was read in
full:

| Entry | Bytes | SHA-256 |
|---|---:|---|
| `OPT-010.patch` | 141412 | `b716bf8806049ada73bfa4cf3a3488970747b3dd31df8715cfa5fc81a098a31a` |
| `OPT-010_CHANGED_FILES.txt` | 1479 | `50fb6848b9f6014a1e4f3a26263670ac6dd030a72494c6f65b37f70607fe71ca` |
| `OPT-010_IMPLEMENTATION_PLAN.md` | 6447 | `2780511b063e15197758cc018c8529cbdc6c740df5ca24c35940fa874c192f2c` |
| `OPT-010_CODEX_HANDOFF.md` | 6867 | `cf05ba6504f88858b599ca4786f44d3ea253ec87c39a8c4241950c2545549cae` |

The patch was authored against provisional base
`00cb851d855b1a980439fb549af30059cf8b3e97`, not the accepted base. A read-only
`git apply --check --whitespace=nowarn -` against `a33f46c...` exits zero, so it is
textually applicable. It is **not semantically applicable as-is**. It is partially reusable
only after material reconciliation: accepted Stage 9 now contains Gameweek appearance data
and stronger artifact/path contracts, while the proposal duplicates those contracts and
invents a manager-capability envelope that the rules system does not have.

## 2. Authority and non-negotiable boundary

Resolve A10 through `specs/manifests/authority_manifest.json` and
`specs/manifests/stage_authority_requirements.json`. In particular, preserve the accepted
DMFP-20 decisions required for `A10-one-GW-optimiser`, the Stage 9 public contracts, and the
rules-capability boundary. The most relevant repository locators are:

- `specs/approved/DMFP-02_FPL_RULES_SCORING_AND_SEASON_CONFIGURATION.txt`;
- `specs/approved/DMFP-09_FPL_POINTS_DISTRIBUTION_ENGINE.txt`;
- `specs/approved/DMFP-10_UNCERTAINTY_SCENARIOS_AND_EARLY_SEASON_POLICY.txt`;
- `specs/approved/DMFP-12_SQUAD_TRANSFER_AND_LINEUP_OPTIMISER.txt`;
- `specs/approved/DMFP-15_BACKTESTING_CALIBRATION_AND_BENCHMARKS.txt`;
- `specs/approved/DMFP-19_CODEX_IMPLEMENTATION_ROADMAP_AND_ACCEPTANCE_TESTS.txt`, section 16;
- `specs/approved/DMFP-20_ASSUMPTIONS_DECISIONS_AND_OPEN_QUESTIONS.txt`;
- `docs/implementation/DMF_PULSE_CODEX_IMPLEMENTATION_PLAYBOOK_v1.txt`, section 23.

The objective must be named exactly
`EXPECTED_CURRENT_GAMEWEEK_MANAGER_POINTS`. It is an A10 bounded proof objective, not the
long-horizon production policy selected by ADR-PROD-002. Every output must state that
limitation. No transfer, hit, free-transfer, bank transition, selling-price, chip, future
Gameweek, ACT/WAIT, price forecast, rank/EO, UI, or FPL write-action concept belongs in this
ticket.

## 3. Resolved Gate 0 rulings

The executable values are frozen in `tickets/OPT-010/ticket.yaml`; Luna may not vary them.

1. `FIXED_SQUAD` is an approved stateless 15-player tactical candidate, never manager/economic
   state. `PROVIDED_SQUADS` and preflight-bounded `BOUNDED_PLAYER_POOL` are also supported.
2. Production conservatively requires the existing `FULL_SEASON` capability. The current target
   returns `BLOCKED/MANAGER_TACTICS_CAPABILITY_UNAVAILABLE`; no new capability is in scope.
3. TEST/REPLAY uses only a complete `REFERENCE_ONLY` or test-synthetic compiled ruleset. Exact
   golden values and the test-only multiple-absence interpretation are ticket-owned and make no
   2026/27 claim.
4. Search is dependency-free exact exhaustive search within the declared bounded scope only.
   There is no unrestricted pool, Pyomo/HiGHS, heuristic pruning or partial optimum.
5. Packaged caps are 12 squad candidates, 5,000,000 tactical configurations, 20,000,000
   scenario-score operations and 16 returned exact ties. There is no objective tolerance or
   invented wall-clock threshold.
6. `RESOURCE_LIMIT` has no recommendation, ties or incumbent and guarantee `NONE`.
7. CLI uses explicit offline request/Gameweek/rules/capability/artifact paths; no ID resolver.
8. Stage-9 `PASS` is eligible; `CONTINUE` and `BLOCKED` both return typed `BLOCKED` before
   search with their upstream status/reasons and no plan.
9. Objective is exactly `EXPECTED_CURRENT_GAMEWEEK_MANAGER_POINTS` with all bounded limitations.
10. No semantic baseline exists; tests may name only a synthetic/reference comparator.
11. `BOUNDED_PLAYER_POOL` enforces compiled initial-squad budget against initial selection cost.
    Fixed/provided modes have no cost or budget semantics, and requests carry no budget value.
12. Stage 9 remains frozen. Production also fails closed with
    `STAGE9_CUTOFF_LINEAGE_UNAVAILABLE` if capability passes but cutoff identity remains
    independently unprovable.

## 4. Exact accepted upstream interfaces to consume

Stage 10 must consume accepted models; it must not serialize local copies of them inside its
request.

| Accepted interface | Required use in Stage 10 |
|---|---|
| `dmf_pulse.fpl_points.models.GameweekProjectionResult` | The single projection input. Verify its embedded `result_sha256` and detached artifact digest at the file boundary. Use `scenario_set`, `joint_matrix`, `monte_carlo` and their accepted lineage. |
| `GameweekScenarioSet` | Authoritative Gameweek/scenario universe: `gameweek_id`, `scenarios`, `player_ids`, `ruleset_hash`, `assembly_mode`, BPS/confidence fields, model/dataset/source bundle IDs, Stage 8 hashes, fixture-result hashes and warnings. |
| `GameweekPointScenario` | Authoritative scenario-level `scenario_id`, `outcome_draw_id`, `weight`, `player_points`, `player_minutes`, `player_appeared`, fixture IDs, assembly mode and approximation labels. Use `player_appeared` directly. Never infer appearance from points or rebuild it from fixture projections. |
| `JointScenarioMatrix` | Audit/cross-check of identical scenario IDs, outcome-draw IDs, weights, player ordering and point rows. Tactical scoring needs `GameweekPointScenario` because the matrix intentionally contains no appearance values. Do not optimize marginals or rebuild a distribution. |
| `GameweekAssemblyMode` | Preserve `BLANK`, `SINGLE_FIXTURE` and `SHARED_OUTCOME_DRAW`. In a blank Gameweek retain the accepted one all-zero/nonappearance scenario. In a DGW use the accepted aggregate points/minutes/appearance and shared draw identity without per-fixture reconstruction. |
| `MonteCarloDiagnostics` | Propagate `stopping_result`, reasons, effective sample size and error information. Solver optimality is only conditional on this upstream scenario set. |
| `dmf_pulse.fpl_points.artifacts` | Reuse `canonical_json_bytes`, `semantic_sha256`, `persist_model_artifact`/equivalent write-once behavior and `load_verified_model`. Preserve canonical compact sorted JSON plus newline, embedded semantic hash, detached file hash, safe path segments and root containment. |
| `dmf_pulse.fpl_points.models.PlayerPosition` | Use the existing `GK`, `DEF`, `MID`, `FWD` enum. Do not introduce a second position enum. |
| `dmf_pulse.rules.models.CompiledRuleset` | The authoritative manager-rules source. Verify compiler integrity and require `compiled.ruleset_hash == projection.scenario_set.ruleset_hash`. |
| `RuleCapability`, `CapabilityArtifact`, `compile_capability_artifact`, `load_capability_artifact` | Recompute the selected capability from the exact compiled rules and compare the canonical artifact/hash. Do not trust user-authored eligibility booleans. `CapabilityArtifact` has no `ruleset_hash`; do not invent one. |
| `dmf_pulse.cli.app.app` | Register one new `optimise` Typer group without changing existing commands, exception behavior or import-time side effects. |

Before scoring, add a Stage 10 compatibility assertion that the matrix scenario IDs,
outcome-draw IDs, weights and point rows exactly correspond to `scenario_set.scenarios` in
their declared player order. This is validation of the accepted object, not a new upstream
representation.

Current production reality must be represented exactly:

- target ruleset `fpl-2026-27` has ruleset hash
  `c9fee6287bcb12170aa2f046d486dd812cfa0404efe214344e39f5aeb739cccf`, status
  `CAPTURED_UNVERIFIED`, and is not globally production eligible;
- `PLAYER_POINTS` capability hash
  `68898c5c9c4f2e2b14001cc1a1625a169eb9858fe20b7e31a45c359077bdec51` is source-backed
  and production eligible;
- `gw1_initial_squad_rules_not_yet_promoted` and
  `automatic_substitution_rules_not_yet_promoted` remain blockers;
- therefore `PLAYER_POINTS` can authorize Stage 9 points only. It cannot authorize squad,
  formation, bench, autosub, captain or vice semantics.

Production must return typed status `BLOCKED` with code
`MANAGER_TACTICS_CAPABILITY_UNAVAILABLE` and no plan while the governing capability is
unavailable. TEST/REPLAY may use a complete accepted `REFERENCE_ONLY` or synthetic compiled
ruleset through the rules adapter; it may not embed arbitrary rule literals in an optimization
request.

## 5. Public contracts to introduce

All Pydantic models are frozen, `extra="forbid"`, finite-number only and canonicalizable.
IDs at the Stage 10 boundary are canonical UUID strings where the repository's identity
contract requires UUIDs. Tuples are canonical-sorted unless their order is semantic, such as
bench priority or scenario order.

### 5.1 Input and policy contracts

Introduce these exact concepts in `src/dmf_pulse/optimisation/schemas.py`:

```python
class OptimisationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    BLOCKED = "BLOCKED"
    INFEASIBLE = "INFEASIBLE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"

class SearchScope(StrEnum):
    FIXED_SQUAD = "FIXED_SQUAD"
    PROVIDED_SQUADS = "PROVIDED_SQUADS"
    BOUNDED_PLAYER_POOL = "BOUNDED_PLAYER_POOL"

class OptimalityGuarantee(StrEnum):
    EXACT_FIXED_SQUAD = "EXACT_FIXED_SQUAD"
    EXACT_PROVIDED_SET = "EXACT_PROVIDED_SET"
    EXACT_DECLARED_PLAYER_POOL = "EXACT_DECLARED_PLAYER_POOL"
    NONE = "NONE"

class CandidatePlayer(OptimisationModel):
    player_id: str
    club_id: str
    position: PlayerPosition
    initial_selection_cost_tenths: NonNegativeInt | None

class CandidatePoolSnapshot(OptimisationModel):
    schema_version: Literal["one-gameweek-candidate-pool-v1"]
    information_cutoff_utc: str
    players: tuple[CandidatePlayer, ...]
    source_bundle_ids: tuple[str, ...]
    snapshot_sha256: Sha256

class CandidateSquad(OptimisationModel):
    player_ids: tuple[str, ...]

class OneGameweekOptimisationRequest(OptimisationModel):
    schema_version: Literal["one-gameweek-optimisation-request-v1"]
    request_id: str
    projection_mode: ProjectionMode
    gameweek_id: str
    information_cutoff_utc: str
    search_scope: SearchScope
    candidate_pool: CandidatePoolSnapshot
    fixed_squad_ids: tuple[str, ...] | None
    provided_candidate_squads: tuple[CandidateSquad, ...]
    required_player_ids: tuple[str, ...]
    excluded_player_ids: tuple[str, ...]
    request_sha256: Sha256

class OneGameweekOptimiserPolicy(OptimisationModel):
    schema_version: Literal["one-gameweek-optimiser-policy-v1"]
    max_squad_candidates: PositiveInt
    max_tactical_configurations: PositiveInt
    max_scenario_score_operations: PositiveInt
    max_returned_ties: PositiveInt
```

The approved ticket must make the fields mutually coherent:

- `FIXED_SQUAD` requires exactly one fixed squad, forbids provided squads and player-pool
  selection, and does not import bank/transfer semantics.
- `PROVIDED_SQUADS` requires a nonempty explicitly bounded set and proves only the optimum of
  that complete set.
- `BOUNDED_PLAYER_POOL` uses `initial_budget_tenths` extracted from compiled rules and exhausts
  every legal squad from the declared player snapshot or returns `RESOURCE_LIMIT` before work.
- required/excluded IDs must be disjoint and present in the candidate snapshot; every selected
  candidate must also be present in the Stage 9 player universe.
- the request never embeds Stage 9 points, appearances, a compiled rules copy, a capability
  evidence copy, or arbitrary resource caps.
- policy loads from the byte-synchronized packaged resource. Tests may inject a model. The CLI
  must not accept a mutable policy file that can raise the governed cap.
- there is no objective tolerance. Compare the exact weighted integer-score numerator. A tie
  exists only when those numerators are exactly equal.

`CandidatePlayer.initial_selection_cost_tenths` is required only for `BOUNDED_PLAYER_POOL`.
It is ignored in fixed/provided modes, whose plan cost/budget fields are null. There is no
request budget; no value has current-manager purchase, selling, affordability or bank meaning.

Add a rules-owned frozen `OneGameweekRulesView` and builder in
`src/dmf_pulse/rules/one_gameweek.py`. It contains only values extracted from the verified
compiled rules: ruleset identity/hash, capability identity/hash where applicable, squad size,
position quotas, initial budget basis where approved, maximum per club, XI/bench sizes,
formation bounds, captain multiplier, vice fallback and the exact automatic-substitution
policy. No optimizer file contains fallback rule constants.

### 5.2 Evaluation, legality and result contracts

Introduce:

```python
class TacticalConfiguration(OptimisationModel):
    starting_xi: tuple[str, ...]
    bench_goalkeeper: str
    bench_order: tuple[str, str, str]
    captain: str
    vice_captain: str

class AutosubEvent(OptimisationModel):
    player_out: str
    player_in: str
    bench_slot: PositiveInt
    reason_code: str

class CaptainResolution(StrEnum):
    CAPTAIN = "CAPTAIN"
    VICE_CAPTAIN = "VICE_CAPTAIN"
    NEITHER = "NEITHER"

class ScenarioManagerScore(OptimisationModel):
    scenario_id: str
    outcome_draw_id: str
    counted_player_ids: tuple[str, ...]
    autosubs: tuple[AutosubEvent, ...]
    captain_resolution: CaptainResolution
    effective_captain_id: str | None
    base_points: int
    captain_bonus_points: int
    bench_contribution_points: int
    manager_points: int

class PointMass(OptimisationModel):
    points: int
    probability: Decimal

class PointDistributionSummary(OptimisationModel):
    pmf: tuple[PointMass, ...]
    expected_points: Decimal
    minimum: int
    p10: int
    median: int
    p90: int
    maximum: int
    probability_field_11: Decimal
    probability_field_10_or_fewer: Decimal
    captain_fallback_probability: Decimal
    captain_and_vice_failure_probability: Decimal
    expected_bench_contribution: Decimal
    component_means: dict[str, Decimal]
    component_covariance: dict[str, dict[str, Decimal]]

class LegalityIssue(OptimisationModel):
    code: str
    message: str
    player_ids: tuple[str, ...]
    rule_paths: tuple[str, ...]

class LegalityReport(OptimisationModel):
    legal: StrictBool
    issues: tuple[LegalityIssue, ...]

class SolverStatus(OptimisationModel):
    backend: Literal["DETERMINISTIC_EXHAUSTIVE_ENUMERATOR"]
    termination: Literal["OPTIMAL", "INFEASIBLE", "RESOURCE_LIMIT", "BLOCKED"]
    search_scope: SearchScope
    guarantee: OptimalityGuarantee
    squad_upper_bound: NonNegativeInt
    tactical_upper_bound: NonNegativeInt
    scenario_operation_upper_bound: NonNegativeInt
    squad_candidates_evaluated: NonNegativeInt
    legal_squads_evaluated: NonNegativeInt
    tactical_configurations_evaluated: NonNegativeInt
    scenario_operations_evaluated: NonNegativeInt
    objective_value: Decimal | None
    best_bound: Decimal | None
    absolute_gap: Decimal | None
    relative_gap: Decimal | None
    tied_optima_total: NonNegativeInt
    returned_ties: NonNegativeInt
    ties_truncated: StrictBool

class OptimisationLineage(OptimisationModel):
    stage9_result_sha256: Sha256
    stage9_artifact_sha256: Sha256
    stage9_scenario_set_sha256: Sha256
    stage9_joint_matrix_sha256: Sha256
    candidate_pool_sha256: Sha256
    request_sha256: Sha256
    ruleset_hash: Sha256
    manager_capability: str | None
    manager_capability_hash: Sha256 | None
    policy_sha256: Sha256
    input_sha256: Sha256

class ExplanationItem(OptimisationModel):
    code: str
    message: str
    player_ids: tuple[str, ...]
    rule_paths: tuple[str, ...]
    metrics: dict[str, Decimal | int | str]

class OneGameweekPlan(OptimisationModel):
    squad: tuple[str, ...]
    tactical_configuration: TacticalConfiguration
    total_cost_tenths: NonNegativeInt | None
    remaining_budget_tenths: NonNegativeInt | None
    expected_manager_points: Decimal
    point_distribution: PointDistributionSummary
    scenario_scores: tuple[ScenarioManagerScore, ...]
    legality: LegalityReport
    solver_status: SolverStatus
    explanations: tuple[ExplanationItem, ...]
    plan_sha256: Sha256

class OneGameweekOptimisationResult(OptimisationModel):
    schema_version: Literal["one-gameweek-optimisation-result-v1"]
    status: OptimisationStatus
    request_id: str
    gameweek_id: str
    objective: Literal["EXPECTED_CURRENT_GAMEWEEK_MANAGER_POINTS"]
    recommended_plan: OneGameweekPlan | None
    tied_optimal_plans: tuple[OneGameweekPlan, ...]
    solver_status: SolverStatus
    lineage: OptimisationLineage
    upstream_mc_status: Literal["PASS", "CONTINUE", "BLOCKED"]
    upstream_warnings: tuple[str, ...]
    explanations: tuple[ExplanationItem, ...]
    error_code: str | None
    error_message: str | None
    result_sha256: Sha256
```

A non-`SUCCESS` result has no `recommended_plan`, no returned ties, guarantee `NONE`, and a
typed deterministic error. On exact success, `objective_value == best_bound`, both gaps are
zero, and every returned plan carries the identical solver status. Preserve the total number
of exact ties even if only the first approved number is returned. Choose the recommendation
by the canonical signature
`(sorted squad, sorted XI, bench goalkeeper, ordered outfield bench, captain, vice)` only
after exact objective equality is established.

Convert accepted float weights once with `Decimal(str(weight))`. Compare unnormalised weighted
integer-score numerators exactly because every plan shares the same positive denominator.
Normalize only for displayed probabilities/expectations under a local fixed Decimal context;
never use the ambient Decimal context and never use a tolerance to turn a lower objective into
a tie.

Keep deterministic semantic results separate from wall-clock telemetry. The acceptance runner
must retain elapsed time in its command evidence, not inside `result_sha256`. If Sol requires
runtime in the public solver contract, approve a separately hashed operational envelope rather
than making identical inputs produce different result bytes.

### 5.3 Functions and dependency direction

```python
def build_one_gameweek_rules_view(
    *,
    compiled: CompiledRuleset,
    projection_mode: ProjectionMode,
    capability: CapabilityArtifact | None,
) -> OneGameweekRulesView: ...

def evaluate_tactical_configuration(
    *,
    squad: tuple[str, ...],
    configuration: TacticalConfiguration,
    candidates: Mapping[str, CandidatePlayer],
    scenarios: GameweekScenarioSet,
    rules: OneGameweekRulesView,
) -> TacticalValue: ...

def validate_plan_against_request(
    *,
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    rules: OneGameweekRulesView,
    plan: OneGameweekPlan,
) -> LegalityReport: ...

def optimise_one_gameweek(
    *,
    request: OneGameweekOptimisationRequest,
    projection: GameweekProjectionResult,
    compiled_ruleset: CompiledRuleset,
    capability: CapabilityArtifact | None,
    policy: OneGameweekOptimiserPolicy,
) -> OneGameweekOptimisationResult: ...
```

The legality module imports schemas and the rules-owned view/resolver; it does not import the
candidate enumerator, solver or optimizer tactic generator. The solver must call the validator
on its final plan, but the validator must be callable independently by CLI and tests.

The rules-owned autosub resolver returns explicit incoming/outgoing pairs and reason codes.
The optimization module supplies the saved team and authoritative Stage 9 appearance map; it
does not choose the meaning/order of the FPL rules. Captain fallback is evaluated from the
saved starting captain and vice appearance, regardless of automatic substitutions.

The independent test oracle may consume serialized primitive fixtures and public schemas, but
must not import production candidate enumeration, tactical generation, autosub implementation,
legality implementation or solver helpers.

## 6. Exact search and fail-closed behavior

Use a deterministic dependency-free exhaustive enumerator only within an approved bounded
scope.

1. Canonicalize input players/squads and reject invalid supplied squads; never silently drop
   them.
2. Compute conservative combinatorial upper bounds with Python integers before materializing
   any combinations. Include squad candidates, legal/superset tactical configurations and
   scenario score operations.
3. If any upper bound exceeds the packaged cap, return `RESOURCE_LIMIT`, guarantee `NONE`, and
   no actionable plan before enumeration. Do not allocate tuples of every position combination.
4. Generate squads lazily. Validate required/excluded players, uniqueness, exact position
   counts, club maximum and approved budget semantics.
5. Enumerate legal XI, the designated bench goalkeeper, all six outfield bench orders and all
   distinct captain/vice pairs. A proven algebraic decomposition of bench and captain choice is
   allowed only with a differential proof against the independent full oracle; it must not
   change the optimum or tie set.
6. Evaluate every configuration against the same ordered `GameweekPointScenario` collection.
7. Apply the rules-owned autosub and captain resolver in every scenario, retain exact integer
   scenario score, and compute the weighted objective.
8. Use exact objective equality, then the canonical signature for deterministic tie-breaking.
9. Independently validate the selected plan and all returned ties. Any failure is
   `OPTIMISER_EMITTED_ILLEGAL_PLAN`, status `BLOCKED`, and no recommendation.
10. Success is permitted only when the declared scope was fully exhausted. An interrupted or
    capped run is never `OPTIMAL`.

The patch's current full-squad combination materialization, silent rejection of bad provided
squads, tolerance-based tie handling, per-squad tie truncation and mid-search cap handling do
not meet this contract. Its autosub search maximizes the number of substitutes and then a
lexicographic membership vector; that is not a substitute for accepted sequential official
semantics.

DMFP-19/playbook mentions a labelled timeout incumbent, but Gate 0 freezes the narrower A10
behavior: `RESOURCE_LIMIT` exposes no recommendation, returned ties, diagnostic incumbent or
optimality guarantee.

## 7. CLI and artifact contract

Approved offline commands:

```text
dmf optimise one-gameweek \
  --request <request.json> \
  --gameweek-artifact <stage9-gameweek.json> \
  --ruleset <compiled-ruleset.json> \
  [--capability <capability.json>] \
  --artifact-root <directory> \
  --output json

dmf optimise validate-plan \
  --request <request.json> \
  --gameweek-artifact <stage9-gameweek.json> \
  --ruleset <compiled-ruleset.json> \
  [--capability <capability.json>] \
  --artifact <one-gameweek-result.json> \
  --output json
```

Both commands are offline. The first loads and verifies every file independently, executes the
pure service, persists canonical immutable output, and returns a stable one-line JSON command
envelope. Domain status controls stable exit codes: success 0, invalid/integrity input 2,
blocked/infeasible/resource limit a documented nonzero code. The second recomputes hashes,
input bindings, rules/capability gate and legality; checking only JSON shape is insufficient.

Persist results below a safe contained path such as
`<root>/optimisation/one_gameweek/<gameweek-hash>/<request-id>/<file-sha>.json`, with a detached
`.sha256` sidecar. Validate request ID and every path segment and repeat containment checks
after resolution. Same bytes at the same path are idempotent; different bytes collide. Add
Windows and POSIX traversal/symlink assurance. Do not catch broad `Exception` at the artifact
boundary.

The semantic hashes are:

- candidate snapshot: payload with `snapshot_sha256 = null`;
- request: payload with `request_sha256 = null`;
- plan: payload with `plan_sha256 = null`;
- result: payload with `result_sha256 = null`;
- input: canonical object containing the verified request hash, Stage 9 result/artifact hashes,
  candidate snapshot hash, ruleset hash, actual capability identity/hash and packaged policy
  hash.

Every semantic field mutation must invalidate the relevant embedded and detached hash.

## 8. File-by-file disposition of the supplied patch

`APPLY` means the proposed bytes are essentially usable. `ADAPT` means retain a bounded idea or
implementation fragment but reconcile it. `REPLACE` means keep tests/intent as a reference but
rewrite the file around accepted contracts. `DROP` means do not add the proposed file.

| Proposed file | Disposition | Required action/reason |
|---|---|---|
| `src/dmf_pulse/cli/app.py` | ADAPT | Keep the small Typer registration idea, but register the reconciled command and preserve accepted command order/help/import behavior. |
| `config/optimisation/one_gameweek.yaml` | ADAPT | Keep a strict policy file, remove objective tolerance, use the frozen ticket caps, and byte-sync it with the package resource. |
| `fixtures/optimisation/OPT-010/expected.json` | REPLACE | Move to the approved `fixtures/optimisation/one_gameweek/` layout and generate from accepted Stage 9/rules contracts with independently hand-derived exact values. |
| `fixtures/optimisation/OPT-010/request.json` | REPLACE | Remove copied points, appearance, rules and capability evidence; bind the new request/candidate snapshot and separate verified artifacts. |
| `src/dmf_pulse/cli/optimise.py` | REPLACE | Proposed command trusts an all-in-one request and implements `validate-result`; implement the artifact-bound commands in section 7 and stable typed exit behavior. |
| `src/dmf_pulse/optimisation/__init__.py` | ADAPT | Export only the approved public models/functions; do not expose proposal-only matrix/rules copies. |
| `src/dmf_pulse/optimisation/artifacts.py` | ADAPT | Reuse canonical/hash/write-once ideas, but add current safe-segment/root-confinement behavior, narrow exceptions and full input/plan verification. |
| `src/dmf_pulse/optimisation/autosub_evaluator.py` | REPLACE | Move rule meaning to the rules-owned resolver; the proposed global maximum-substitution search is not accepted official ordering and omits outgoing players. |
| `src/dmf_pulse/optimisation/candidate_pool.py` | REPLACE | Use preflight bounds and lazy generation; reject bad supplied squads; never pre-materialize every positional combination or silently discard inputs. |
| `src/dmf_pulse/optimisation/errors.py` | ADAPT | Retain a narrow typed error with stable code/details, but keep user-safe messages and map expected failures to result status/CLI codes. |
| `src/dmf_pulse/optimisation/explain.py` | ADAPT | Retain deterministic structured explanations; remove unauthorized `NO_TRANSFER_BASELINE`, add rule paths, lineage, objective limitation, upstream precision and guarantee scope. |
| `src/dmf_pulse/optimisation/legality.py` | REPLACE | Rebuild as a structurally independent validator over the rules-owned view. Validate the complete supported constraint set and avoid solver imports. |
| `src/dmf_pulse/optimisation/resources/__init__.py` | APPLY | Empty package marker is compatible. |
| `src/dmf_pulse/optimisation/resources/one_gameweek.yaml` | ADAPT | Byte-identical packaged copy of the approved config; remove tolerance/unapproved values. |
| `src/dmf_pulse/optimisation/schemas.py` | REPLACE | Remove `JointScenarioInput`, `AppearanceMatrixInput`, `ManagerRulesCapabilityEvidence` and user-supplied `OneGameweekRules`; introduce the contracts in section 5. |
| `src/dmf_pulse/optimisation/service.py` | REPLACE | Remove the empty hard-coded capability allowlist and embedded baseline path. Load/verify accepted Stage 9 and rules objects, gate by canonical capability, and bind every hash. |
| `src/dmf_pulse/optimisation/solver.py` | REPLACE | Fix exact comparison/tie accounting, preflight caps, lazy enumeration and guarantee scope; never return an unproven recommendation. |
| `src/dmf_pulse/optimisation/tactics.py` | REPLACE | Retain only independently verified arithmetic ideas. Consume `GameweekScenarioSet` directly, use rules-owned autosubs, return full PMF/component covariance and preserve all scenario identities. |
| `src/dmf_pulse/optimisation/upstream.py` | DROP | Accepted `GameweekPointScenario` already has `player_minutes` and `player_appeared`; no appearance reconstruction/parallel hash artifact is needed. Put alignment assertions at the service boundary. |
| `tests/contract/optimisation/test_stage9_compatibility.py` | REPLACE | Test the final accepted Gameweek fields, matrix/scenario alignment, direct appearance use, blank and shared-draw behavior, semantic/detached hashes and mutation rejection. |
| `tests/integration/optimisation/test_one_gameweek_service.py` | REPLACE | Use separate accepted projection/rules/capability/request artifacts and cover all result states, exact scope guarantees, CLI and immutable artifacts. |
| `tests/performance/optimisation/test_smoke_budget.py` | ADAPT | Keep a no-coverage smoke benchmark, but use an approved normal fixture/threshold and assert preflight counters; do not invent a runtime target. |
| `tests/property/optimisation/test_oracle_equivalence.py` | REPLACE | Expand beyond three examples/all-appear cases; generate adversarial legal tiny universes and compare full optimum/tie set/scenario scores with an independent oracle. |
| `tests/support/optimisation_factories.py` | REPLACE | Build accepted `GameweekProjectionResult`, compiled reference rules and candidate snapshot models; do not build copied joint/appearance/rules envelopes. |
| `tests/support/optimisation_oracle.py` | REPLACE | The proposed oracle mirrors production decisions and misses semantics. Implement independently with no production enumerator/autosub/validator helper imports. |
| `tests/unit/optimisation/test_autosubs.py` | REPLACE | Drive accepted rules goldens, outgoing/incoming pairs, multiple absences, GK behavior, order and formation preservation. |
| `tests/unit/optimisation/test_capability_gate.py` | REPLACE | Load/recompile real capability artifacts, prove every non-manager capability including `PLAYER_POINTS` fails, and cover TEST/REPLAY only through accepted compiled rules. |
| `tests/unit/optimisation/test_legality.py` | ADAPT | Keep the core cases, then add every independent squad/XI/bench/captain/candidate/budget/rules constraint and static dependency separation. |
| `tests/unit/optimisation/test_tactics.py` | REPLACE | Use accepted scenarios and exact expected values; add PMF, covariance, both-captains-fail, negative points, blank/DGW and hash/tie cases. |

Disposition totals: 1 APPLY, 9 ADAPT, 18 REPLACE, 1 DROP. Do not run `git apply`; copy only
reviewed fragments into tests-first implementations.

## 9. Required files missing from the proposal

The approved OPT-010 ticket explicitly allows these additions/changes. Exact evidence
filenames are frozen by the ticket schema.

| File/path | Purpose |
|---|---|
| `tickets/OPT-010/ticket.yaml` | Sol/human-owned execution contract, exact base/branch/scope/files/commands. |
| `src/dmf_pulse/rules/one_gameweek.py` | Rules-owned manager-tactics view, production gate and pure official resolver. No capability schema extension without a separate decision. |
| `src/dmf_pulse/optimisation/squad_model.py` | Accepted DMFP-19 boundary for exact squad search/preflight proof; no fake MILP or future transfer model. |
| `tests/unit/rules/test_one_gameweek.py` and `tests/golden/rules/test_one_gameweek.py` | Capability extraction, target fail-closed behavior and accepted autosub/captain rule examples. |
| `tests/unit/optimisation/test_candidate_pool.py`, `test_solver.py`, `test_schemas.py`, `test_artifacts.py`, `test_service.py`, `test_explain.py` | Focused boundary/branch coverage instead of oversized integration tests. |
| `tests/golden/optimisation/test_one_gameweek.py` | Byte-exact request/result/CLI goldens and exact hand-derived scores. |
| `tests/assurance/optimisation/test_artifact_hardening.py` | Traversal, symlink/confinement, collision, canonical/hash and mutation attacks. |
| `fixtures/optimisation/one_gameweek/` | Candidate snapshot, Stage 9 Gameweek result plus sidecar, complete TEST ruleset, request, expected result and adversarial fixtures. |
| `scripts/assurance/check_opt010_scope.py` | Exact parent/allowed-file/exclusion/dependency/migration guard. |
| `scripts/assurance/check_opt010_resources.py` | Source/package policy byte equality and packaged loading. |
| `scripts/assurance/check_opt010_artifact.py` | Independent artifact/hash/lineage/legality verifier. |
| `scripts/verify_opt010_wheel.py` | Offline installed-wheel CLI/resource/RECORD test outside the source tree. |
| `evidence/tickets/OPT-010/` and `evidence/stages/10/` | Exact command ledger, hashes, coverage, runtime, stage acceptance and review findings. |

Do not add a database migration, provider, network adapter, model-training code, API/UI,
execution action, transfer module, or solver dependency in this ticket.

## 10. Implementation and test order

### Implementation order

1. Verify the frozen Gate-0 ticket, create the branch from the exact base, and confirm the
   approved OPT-010 entry in `PLANS.md` before production changes.
2. Freeze JSON/Pydantic contracts, typed status/error codes, policy schema, CLI schema, fixture
   inventory and exact hand-derived expected values in tests.
3. Implement the rules-owned view/gate/resolver and prove production blocks with current target
   artifacts while complete TEST/REPLAY rules work.
4. Implement the Stage 9 compatibility boundary and lineage hashing. Delete the proposal's
   appearance reconstruction concept.
5. Implement independent legality validation before search.
6. Implement exact scenario-level autosub/captain scoring and distribution summaries for one
   supplied tactical configuration.
7. Implement the independent test oracle and make it pass deterministic examples before
   writing production enumeration.
8. Implement lazy squad/tactical generation, conservative preflight counting, exact objective
   comparison, complete ties and deterministic signature.
9. Compose the service, revalidate every selected/tied plan, and add structured explanations.
10. Add canonical immutable artifacts and the offline CLI.
11. Add scope/resource/artifact/wheel assurance, command evidence and the capped review pack.
12. Run focused gates at each checkpoint, then every literal acceptance command from a clean
    installed wheel. Independent review remains separate; Luna does not self-accept or merge.

### Test order and minimum cases

1. **Contract first:** strict request/result/CLI schemas; accepted Stage 9 model and hash loading;
   scenario/matrix alignment; ruleset hash binding; canonical candidate snapshot; no copied
   appearance/rules input.
2. **Rules/gate:** `PLAYER_POINTS`, `GW1_INITIAL_SQUAD`, `TRANSFER_STATE`, `CHIP_STATE` and blocked
   `FULL_SEASON` cannot leak eligibility; forged capability fields/hash fail; target production
   blocks; accepted REFERENCE_ONLY/synthetic TEST/REPLAY succeeds; projection/rules mismatch
   blocks.
3. **Legality unit:** squad size/uniqueness, exact position quotas, club maximum, approved budget,
   required/excluded IDs, missing Stage 9 player, exactly 11 starters, formation min/max, one
   starting GK, designated remaining GK, outfield bench is exactly the remaining three in a
   permutation, captain/vice distinct and both in the saved XI.
4. **Rules/autosub golden:** no substitution, ordinary first-bench substitution, first bench
   absent, first bench skipped to preserve formation, multiple absent starters with official
   ordering, starting GK replaced only by the designated appearing bench GK, absent bench GK,
   and no hindsight selection.
5. **Tactical exact examples:** captain appears; captain fails and vice receives the multiplier;
   both fail; negative Stage 9 points remain counted when the player appeared; nonappearance is
   read from `player_appeared`; bench contribution, exact PMF, quantiles, component means and
   covariance. A canonical two-scenario captain fixture should score 20 and 8 with weights
   1/2, hence expected manager points 14.
6. **Stage 9 modes:** blank Gameweek produces exact zero and deterministic ties; single fixture;
   `SHARED_OUTCOME_DRAW`/multiple fixture uses aggregate Gameweek points and appearance; correlated
   nonappearance changes autosub/captain value without marginal reconstruction; approximation
   labels/warnings propagate.
7. **Solver:** infeasible position/club/budget pools, fixed squad, provided complete set, bounded
   player pool, exact exhaustive optimum, exact ties, total tie count/truncation, canonical
   tie-break, no tolerance near-tie, conservative preflight cap, actual counter guard and no plan
   on resource limit.
8. **Independent oracle/Hypothesis:** at least the approved nontrivial profile (recommended 100+
   examples in normal CI) across small legal/adversarial universes; compare objective numerator,
   complete optimum signature set, every scenario score and legality. The test fails if the
   oracle imports production search/autosub/legality helpers.
9. **Hash/adversarial:** mutate every point, weight, appearance, outcome/scenario order, player
   metadata, rule/capability/policy/request field, plan and explanation; reject stale embedded or
   detached hashes, duplicate/unknown IDs, NaN/infinity, unsafe paths, collisions and escapes.
10. **Deterministic replay/golden:** same canonical inputs produce byte-identical semantic result,
    plan/result hashes and chosen tie on Windows and POSIX. Runtime telemetry is tested
    separately.
11. **Integration/CLI:** success, blocked capability, infeasible, resource limit, validate-plan,
    immutable write/reload/collision, installed wheel outside repository, offline/no PYTHONPATH,
    packaged policy and stable exit codes.
12. **Performance and regression:** approved normal fixture without coverage instrumentation;
    Stage 2 rules and Stage 9 suites; full repository branch coverage; wheel RECORD; no migration,
    dependency, secret or scope drift.

## 11. Commands Luna should execute

The ticket's `acceptance_commands` list is literal and controlling; every exit code must be
checked. The branch-creation command below is for the later implementation run, not this plan.

### Start and invariants

```powershell
git fetch origin
git rev-parse main
git rev-parse origin/main
git status --short --branch
git switch -c stage/A10/OPT-010-one-gameweek-optimiser a33f46cd7ec190fbd4959e2840527116f22547ac
git rev-parse HEAD
git merge-base HEAD a33f46cd7ec190fbd4959e2840527116f22547ac
uv sync --all-groups --frozen
uv tree --depth 1
uv run alembic heads
```

Assert the three revision commands return the approved base/descendant relation, the initial
branch is clean, dependency output contains no unapproved package, and Alembic reports only
`20260807_0006 (head)`.

### Focused and static gates

```powershell
git diff --check
uv run python scripts/assurance/check_opt010_scope.py --root . --parent-revision a33f46cd7ec190fbd4959e2840527116f22547ac --ticket tickets/OPT-010/ticket.yaml
uv run python scripts/assurance/check_opt010_resources.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src/dmf_pulse
uv run pytest -q tests/unit/rules/test_one_gameweek.py tests/golden/rules/test_one_gameweek.py
uv run pytest -q tests/unit/optimisation tests/contract/optimisation
uv run pytest -q tests/property/optimisation tests/golden/optimisation tests/integration/optimisation tests/assurance/optimisation --cov=src/dmf_pulse/optimisation --cov-branch --cov-report=term-missing --cov-report=json:evidence/stages/10/coverage.json
uv run pytest -q tests/performance/optimisation
```

The ticket's coverage verifier must require at least 95% branch coverage for the deterministic
rules/autosub/legality/scoring/hash core, per the implementation playbook, and must not hide
uncovered branches with broad pragmas.

### Inherited and repository gates

```powershell
uv run pytest -q tests/unit/rules tests/property/rules tests/golden/rules
uv run pytest -q tests/unit/fpl_points tests/property/fpl_points tests/contract/fpl_points tests/golden/fpl_points tests/integration/fpl_points tests/assurance/fpl_points
docker compose -f compose.test.yaml config --quiet
docker compose -f compose.test.yaml up -d --wait
uv run python scripts/test_migration_matrix.py --baseline-revision 20260803_0005 --target head
uv run pytest -q -m "postgres and integration" tests/integration
docker compose -f compose.test.yaml down -v --remove-orphans
uv run pytest -q --ignore=tests/performance --cov=dmf_pulse --cov-branch --cov-report=json:evidence/stages/10/repository_coverage.json
```

The ticket acceptance script must place Docker teardown in `finally`, as the current repository
script does.

### Public CLI, artifact and wheel gates

```powershell
$OptRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dmf-opt010-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $OptRoot | Out-Null
uv run dmf optimise one-gameweek --request fixtures/optimisation/one_gameweek/request.json --gameweek-artifact fixtures/optimisation/one_gameweek/stage9_gameweek_result.json --ruleset fixtures/optimisation/one_gameweek/reference_ruleset_test_only.json --artifact-root $OptRoot --output json
uv run dmf optimise validate-plan --request fixtures/optimisation/one_gameweek/request.json --gameweek-artifact fixtures/optimisation/one_gameweek/stage9_gameweek_result.json --ruleset fixtures/optimisation/one_gameweek/reference_ruleset_test_only.json --artifact <artifact-path-from-command> --output json
uv run python scripts/assurance/check_opt010_artifact.py <artifact-path-from-command> --request fixtures/optimisation/one_gameweek/request.json --gameweek-artifact fixtures/optimisation/one_gameweek/stage9_gameweek_result.json --ruleset fixtures/optimisation/one_gameweek/reference_ruleset_test_only.json
uv build
uv run python scripts/verify_opt010_wheel.py
uv run python scripts/generate_repository_manifest.py --ticket OPT-010
uv run python scripts/validate_repository.py
uv run python scripts/scan_secrets.py
git diff --check
git status --short
```

Also assert `git diff a33f46cd7ec190fbd4959e2840527116f22547ac -- pyproject.toml uv.lock` and the
migration directory diff are empty unless a prior Sol decision explicitly changed that
constraint. Generate the capped `review_pack/` only after exact command evidence is final.

## 12. Decisions Luna is not authorized to make

Luna must stop and escalate rather than:

- change the approved ticket or its allowed-file/acceptance contract;
- infer 2026/27 squad, formation, autosub, captain, vice, budget or price semantics;
- treat `PLAYER_POINTS production_eligible=true` as manager-tactics eligibility;
- add a hard-coded manager capability allowlist or trust request-supplied capability booleans;
- add/change a `RuleCapability`, dependency path or capability schema;
- replace the frozen conservative `FULL_SEASON` production gate or add a narrow capability;
- resolve multi-missing-player autosub ordering without accepted official examples;
- infer appearance from zero/nonzero points or rebuild accepted Stage 9 scenarios;
- optimize marginal expected points, independently sample players, reorder scenarios or drop
  correlation/shared-draw identities;
- reinterpret the frozen stateless squad, absent baseline or initial-selection-cost semantics;
- introduce candidate pruning/top-K/heuristic search and label it a full-pool optimum;
- change packaged caps, invent a runtime threshold, expose an incumbent or add objective
  tolerance;
- add Pyomo, HiGHS or any dependency; change `pyproject.toml`/`uv.lock` without approval;
- mutate a frozen Stage 9 public contract merely to add projection mode/cutoff or an ID resolver;
- assert production cutoff provenance that `GameweekProjectionResult` does not carry;
- change the expected-points objective, add risk/rank/EO utility, or implement Stage 11+ state;
- add a migration, network/provider access, credential handling, UI/API or FPL write action;
- lower inherited coverage/security/artifact/wheel gates, self-accept, merge or publish.

## 13. Resolved contradictions and future intervention boundary

| Former blocker | Frozen OPT-010 ruling |
|---|---|
| Missing ticket | `tickets/OPT-010/ticket.yaml` is `READY` and controlling. |
| Current-squad wording | `FIXED_SQUAD` is a stateless 15-ID tactical candidate, never manager state. |
| Missing narrow capability | Production conservatively requires existing `FULL_SEASON`; current target is typed `BLOCKED`. A narrow capability is a future rules ticket. |
| Target autosub uncertainty | Production remains blocked. Ticket goldens freeze a test-only reference interpretation without a 2026/27 claim. |
| Full-pool/MILP tension | Only fixed, complete provided-set and preflight-bounded declared-pool exhaustion are supported; no Pyomo/HiGHS. |
| Caps/runtime | Packaged caps are 12, 5,000,000, 20,000,000 and 16; wall time is telemetry only. |
| Timeout incumbent | No plan, ties or incumbent on `RESOURCE_LIMIT`. |
| CLI ID resolver | Explicit offline artifact paths only. |
| Stage-9 cutoff gap | No Stage-9 change; production returns `STAGE9_CUTOFF_LINEAGE_UNAVAILABLE` after a passing capability gate. |
| One-GW versus season objective | Result always labels the exact bounded A10 objective and its limitations. |
| Monte Carlo `CONTINUE` | Typed `BLOCKED/UPSTREAM_MONTE_CARLO_CONTINUE` before search; no diagnostic plan. |
| Baseline wording | No semantic baseline; only named test comparator evidence. |

There is no remaining implementation blocker. Any desired change to these rulings is outside
Luna's authority and requires a new Sol/human governance amendment or separate ticket.

## 14. Concise acceptance checklist

- [ ] Exact parent/branch/ticket/allowed-file checks pass; initial worktree was clean.
- [ ] Gate 0 decisions are recorded; no semantic decision remains for Luna.
- [ ] Production blocks on current manager rules; no `PLAYER_POINTS` leakage.
- [ ] TEST/REPLAY rules are complete, accepted and explicitly labelled.
- [ ] Accepted Stage 9 Gameweek scenarios/appearances are consumed directly and cross-checked
  against the joint matrix.
- [ ] Blank, single-fixture and shared-draw/DGW behavior is preserved with lineage/warnings.
- [ ] Independent legality validator covers every supported squad/tactical constraint.
- [ ] Rules-owned autosub/GK/captain/vice resolution passes official/adversarial goldens.
- [ ] Exact scenario scores, PMF, expectation and covariance pass hand-derived fixtures,
  including negative points and correlated nonappearance.
- [ ] Independent oracle proves the complete optimum and tie set on property-generated tiny
  universes without importing production enumeration helpers.
- [ ] Preflight caps are conservative; no materialized combinatorial explosion; resource limit
  returns no recommendation and no false optimality.
- [ ] Exact tie comparison and canonical tie-break are deterministic; full tie count is retained.
- [ ] Request/input/plan/result and detached artifact hashes fail on every semantic mutation.
- [ ] CLI optimize/validate-plan artifacts are immutable, confined, offline and stable.
- [ ] Focused 95% critical branch gate, inherited Stage 2/9 suites, full repository coverage,
  performance, build and isolated-wheel tests pass.
- [ ] No dependency/lock, Alembic head, migration, secret, network, scope or future-stage drift.
- [ ] Evidence hashes/manifest/review pack validate; independent reviewer has no unresolved
  P0/P1. Human acceptance and merge remain separate.
