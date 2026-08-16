# OPT-010 R2 blocker: governed installed-CLI success fixture

Status: `RESOLVED_FOR_R2E_TARGETED_PASS`  
Recorded: 2026-08-16  
Remediation parent: `3f1550e3838e6f44c31990dcf83b2bc6ed7dc6fd`

## Exact conflict

The frozen ticket requires both a successful TEST/REPLAY CLI solve and a successful
`validate-plan` execution from a clean installed wheel.  It also requires TEST/REPLAY to use
only a complete, integrity-checked `REFERENCE_ONLY` (or test-synthetic) compiled ruleset
(`tickets/OPT-010/ticket.yaml`, `gate0_rulings.G0-3` and R2D P2-02).

The sole governed `REFERENCE_ONLY` RUL-002 source fixture is schema `1.0`:

- `fixtures/rules/RUL-002/reference_2025_26/season_manifest.yaml:3-6`
- `fixtures/rules/RUL-002/synthetic_complete/season_manifest.yaml:3-6`

Schema `1.0` has no `rules.lineup.automatic_substitutions` field.  OPT-010 must resolve that
field to construct its rules view (`src/dmf_pulse/rules/one_gameweek.py:124-191`), because the
frozen ticket explicitly requires the automatic-substitution semantics
(`ticket.yaml`, `reference_test_rules.automatic_substitutions`).

The only repository rules artifact with those fields is
`artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json`; it is deliberately
`CAPTURED_UNVERIFIED`.  TEST/REPLAY rejects it under the frozen eligibility gate
(`src/dmf_pulse/rules/one_gameweek.py:112-118`).  Reclassifying or copying that target-season
artifact as `REFERENCE_ONLY` would invent a governed lifecycle/authority state.  The ticket
also explicitly forbids changes to rules authoring, rules models, capabilities, rule fixtures,
and compiled rules artifacts.

The test-only in-memory helper may construct a synthetic `CompiledRuleset`, but it cannot be
used as an integrity-checked, governed external rules artifact in an installed-wheel CLI proof.
Using it to manufacture a committed success fixture would bypass the frozen G0-3 boundary.

## Consequence

P1-07/P2-02 cannot be closed honestly: `run_opt010_cli_acceptance.py` can prove the required
current-target blocked result, but it cannot also prove the required success and
`validate-plan` paths from the approved fixture set.  Consequently the full 31-command final
ledger, exact-head acceptance evidence, and fresh Sol rereview are not eligible to be claimed.

## Required authority resolution

Provide one of the following before resuming:

1. A governed, integrity-checked schema-1.1 `REFERENCE_ONLY` fixture that contains the frozen
   automatic-substitution values and is explicitly approved for the installed CLI proof; or
2. An accepted amendment to the frozen ticket that removes/replaces the successful installed
   TEST/REPLAY CLI and `validate-plan` requirement.

No implementation, capability-schema, lifecycle, or fixture-authoring change had been made at
the point this blocker was recorded.

## R2E authority resolution

The architecture/governance ruling authorized the first option above as a narrow additive
ticket exception. `tickets/OPT-010/ticket.yaml` now permits a wholly test-synthetic schema-1.1
compiled ruleset only under `fixtures/optimisation/one_gameweek/**`, while preserving all
production, target-season, capability-schema, Stage-9, and Stage-11 boundaries.

The source fixture compiles normally to `reference_ruleset_test_only.json` with:

- ruleset identity `opt010-test-synthetic`;
- lifecycle `REFERENCE_ONLY`;
- `production_eligible: false`;
- no target-season checked claims; and
- canonical ruleset hash
  `adb24ef11bae13a131dd27434ad87e43a1a0dbbff95ba5f70c89aafbe6ebe188`.

The authoring amendment only permits `REFERENCE_ONLY` schema-1.1 sources without target-season
claims. Existing `CAPTURED_UNVERIFIED`, `VERIFIED`, and `ACTIVE` target-claim validation remains
enforced, and no existing production or target-season artifact was reclassified or copied.

The focused R2E proof passed for canonical fixture loading, frozen manager-tactics values,
production rejection, current-target blocking, source-tree one-gameweek and `validate-plan`,
and offline installed-wheel isolation. The governance blocker is therefore resolved for the
targeted pass. The comprehensive 31-command ledger, repository test/coverage run, final
evidence refresh, and independent Sol review remain intentionally deferred.

## R2G platform-portable acceptance invocation resolution

The R2F preflight established that Windows Application Control blocks the generated `mypy`
console launcher with os error 4551, while `uv run python -m mypy` executes the locked module.
The repository owner authorized a narrow ticket amendment that makes only the listed
`python -m mypy` and `python -m pytest` forms canonical OPT-010 acceptance commands. It changes
command launch form only: all selected targets, arguments, thresholds, policy, and production
semantics remain frozen. No full acceptance was run after this environment blocker; a fresh
ledger is required against the R2G governance commit.

## R2H acceptance-order resolution

The first R2G ledger was invalidated at repository coverage: the prior sequence required its
mandatory compose teardown before a later coverage suite that executes TEST-database integration
tests, and it generated the repository manifest only after that suite had validated it. The
repository owner authorized an additive order-only ticket amendment. It preserves the 31
commands, keeps the TEST database available through repository coverage, moves the existing
manifest command to immediately before coverage, and moves the existing teardown to immediately
afterwards. No rules, fixture, production eligibility, implementation, test selection, or
acceptance threshold changed. The R2G generated outputs are invalidated and must not be used as
final PASS evidence; a new full ledger is required against the R2H governance commit.

## R2H continuation resolution

The replacement R2H ledger reached the repository-wide coverage gate after commands 1–19 had
passed at implementation/governance revision `79102d41fc5d4e2c70d8251d643b705602573045`. An
external runner limit interrupted that one command only. The continuation eligibility proof
established the same revision and tree with no semantic delta, so commands 1–19 were reused
rather than rerun.

The unfinished repository-wide gate is now resolved with the authorized PATH B exact shard
proof: 1,868 collected non-performance nodes, zero overlaps or omissions, every successful
shard recorded, and a final 91.84% combined repository coverage result. The successful CLI,
installed-wheel, specifications, repository-validation, secret-scan, Alembic, dependency-drift,
migration-drift, and final-diff gates are recorded in the continuation ledger. The current
target-season production gate remains correctly blocked with
`MANAGER_TACTICS_CAPABILITY_UNAVAILABLE`.

Status: `RESOLVED_FOR_INDEPENDENT_SOL_REREVIEW`. This records successful completion of the
implementation acceptance evidence only; it is not self-acceptance, human acceptance, or a
merge authorization.
