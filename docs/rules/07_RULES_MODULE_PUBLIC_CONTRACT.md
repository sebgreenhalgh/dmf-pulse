# Rules Module Public Contract

## Stable types

- `FPLPosition`: `GK`, `DEF`, `MID`, `FWD`.
- `RulesetStatus`: `DRAFT_PRELAUNCH`, `REFERENCE_ONLY`, `CAPTURED_UNVERIFIED`, `CONFLICTED`, `VERIFIED`, `ACTIVE`, `SUPERSEDED`, `REVOKED`.
- `VerificationStatus`: `UNKNOWN`, `UNCONFIRMED`, `PROVISIONAL`, `VERIFIED`, `CONFLICTED`, `SUPERSEDED`.
- `AssistEligibility`: `DEFINITE_ASSIST`, `DEFINITE_NO_ASSIST`, `AMBIGUOUS_ASSIST`.
- Explicit domain errors with stable codes.

## Core service interfaces

Names may follow repository conventions, but equivalent typed interfaces must exist:

```python
validate_ruleset_directory(path: Path) -> RulesetValidationReport
compile_ruleset(path: Path) -> CompiledRuleset
load_compiled_ruleset(path: Path) -> CompiledRuleset
diff_rulesets(left: RulesetLike, right: RulesetLike) -> RulesetDiff
activate_ruleset(compiled: CompiledRuleset, approval: ApprovalRecord, registry: Path) -> ActivationReceipt
score_fixture(ruleset: CompiledRuleset, scenario: FixtureScenario) -> FixtureScoreResult
score_gameweek(ruleset: CompiledRuleset, scenario: GameweekScenario) -> GameweekScoreResult
allocate_bonus(bps_by_player: Mapping[PlayerId, int]) -> Mapping[PlayerId, int]
```

## Purity and determinism

- Compilation reads only named input files and writes only through an explicit output operation.
- Scoring functions perform no I/O and are deterministic.
- Runtime rules are loaded by explicit path/hash, never a mutable `latest` global.
- All scenario points and BPS are integers.
- Money values, if compiled, are integer tenths of £1m.
- Datetimes are aware UTC strings internally.

## Scenario identity

Player IDs in synthetic fixtures are opaque strings. They are not canonical provider IDs. A later canonical layer will adapt UUIDs without changing the scorer.

## Assist boundary

RUL-002 does not infer assist eligibility from prose or raw touch chains. A scenario supplies the resolved eligibility state/count under its event generator. The rules engine applies configured points and validates impossible states. Detailed FPL assist classification remains configuration plus later event-scenario work.
