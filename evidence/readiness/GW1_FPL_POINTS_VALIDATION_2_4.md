# GW1 Checkpoint 2.4 - current FPL-points validation

## Scope and identity

- Canonical branch - `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable programme parent - `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Resumed canonical SHA - `5838bc6b1a44070261035c2d3d53b9a77d9d4a3c`.
- Failed Linux workflow/job - `32329591311` / `96307553750`.
- Final capability commit - `PENDING_FINAL_PUBLICATION`.
- Final dedicated Linux workflow - `PENDING_FINAL_PUBLICATION`.
- Real credentialled provider call - `OPERATOR_CHECKPOINT`.
- Accepted current score/player prior artifact - `NOT_SUPPLIED / OPERATOR_BLOCKER`.

## Implemented vertical slice

- `ProjectionMode.PRESEASON_DECISION_SUPPORT` is an explicit public Stage-9
  mode. Existing production checks are unchanged: `PRODUCTION` still requires
  an ACTIVE ruleset and exact human activation bundle. The new current adapter
  accepts only the exact tracked `fpl-2026-27` `VERIFIED` artifact and its
  source-backed, blocker-free `PLAYER_POINTS` capability.
- A deterministic run configuration binds the Checkpoint-2.3 semantic hash,
  information cutoff, common root seed, scenario count, exact rules artifact,
  compiled capability, accepted Monte Carlo policy, and fixture/team/player
  source hashes. It explicitly records that no human activation exists and is
  not represented as an approval.
- Each current fixture is passed to the existing `FplPointsService`; there is no
  second event allocator, scorer or handcrafted xP formula. Every fixture uses
  the same Stage-9 root seed, so the accepted Gameweek assembler receives the
  same outcome-draw identities across fixtures.
- The existing `assemble_gameweek` and `build_gameweek_projection` paths produce
  the joint Gameweek scenario set, player marginals, full PMFs, quantiles,
  components and numerical diagnostics. A small contract-test scenario budget
  truthfully reports Monte Carlo `CONTINUE`; it is not promoted to projection
  acceptance.
- The private transient player table contains official and transient player
  identity, team, position, current price, exact Stage-7 P(start) and expected
  minutes, accepted Stage-9 mean/distribution/quantiles, football and numerical
  uncertainty, scenario identity, cutoff and complete rules/source lineage.
  Its safe summary exposes only counts, confidence, stopping state and hashes.
- Frozen Stage-9 request/result schemas and their manifest now include the new
  explicit mode and reproduce exactly from the existing assurance script.
- Official-FPL raw and derived retention remain denied. The adapter performs no
  provider call, database access or filesystem write and returns the private
  table in memory only.

## Clean-checkout CI remediation

- The failed Linux run completed `493` tests before two failures and six setup
  errors all traced to one reproducibility defect: the new test fixture expected
  the gitignored developer artifact `artifacts/rules/fpl-2026-27.json`.
- The test now compiles tracked `config/rules/fpl-2026-27` with the existing
  compiler into a pytest temporary directory, reloads canonical bytes, and
  independently pins schema, ID, season, version, VERIFIED state, rules hash,
  file hash, and the source-backed blocker-free PLAYER_POINTS capability.
- The rules-drift test now copies and mutates tracked source, then compiles the
  drifted temporary artifact. No generated rules file became source authority.
- The workflow path filters now watch the tracked target rules directory and
  `src/dmf_pulse/rules/**`; the ignored artifact path was removed. Scoring
  semantics, lifecycle state, activation and accepted hashes were not changed.

## Rules governance finding

- The disposable artifact compiled from tracked authority is schema `1.1`,
  ruleset version `1.0.0`, status `VERIFIED`, ruleset hash
  `c2883ad9bf1497dad9c2eba69422e14937ddc072f9b3a95c5005a312c38f7d56`.
- Its freshly compiled `PLAYER_POINTS` capability is source-backed,
  production-eligible and blocker-free at capability hash
  `fafb9518ec25989f6e0470215e83cc61008532b64c5bd5d026b4fb1a897fc5e8`.
- The global ruleset was not relabelled ACTIVE. No human activation was created,
  inferred or fabricated. The tracked pending human-approval state remains
  controlling for production.

## Hostile review

### P0/P1 remediated

1. TEST or REPLAY would misclassify a real pre-GW1 decision-support run. The
   explicit non-production mode now makes the purpose reviewable without
   weakening the production gate.
2. A verified rules path alone could select an older prelaunch artifact. The
   adapter pins and rechecks the canonical file hash, compiled rules identity,
   lifecycle status and independently compiled PLAYER_POINTS capability hash.
3. Fixture projections could use unrelated seeds and lose cross-fixture
   dependence. One config-owned root seed is placed in every request and exact
   shared outcome-draw IDs are required by the accepted Gameweek assembler.
4. A table row could copy a mean while detaching its distribution or upstream
   identity. Bundle validation now reconciles every row's mean, median,
   quantiles, PMF, uncertainty, Stage-7 start/minutes, fixture/result hashes and
   rules provenance to the embedded accepted Stage-9 output.
5. Current names, prices and distributions could leak through a public summary.
   The private table is explicitly transient; disclosure tests prove the safe
   summary contains none of those fields.

### Material limitations retained

- Stage-7 remains an empty-current-history cold start trained on frozen
  synthetic TEST/REPLAY contract data.
- The current team-score and player-allocation artifact is externally governed
  and has not been supplied, so this checkpoint has not produced a real current
  GW1 player table.
- The Stage-9 event-allocation baseline retains the accepted TEMP-EVT-002 and
  TEMP-PTS-001 limitations and confidence grade E in non-production mode.
- Monte Carlo `PASS` is not claimed for the deliberately small synthetic
  contract-test budget; Checkpoint 2.5 must evaluate an operator run at its
  declared scenario budget before projection acceptance.

## Local validation

- Current-points tests - `9 passed` inside the final current group.
- Combined current Stage-7 through Stage-9 branch coverage - `34 passed`,
  `92.27%` total across `1,107` statements and `200` branches; current
  availability measured `93%`, current event handoff `90%`, and current points
  adapter `93%`.
- Final-tree accepted Stage-6 through Stage-9 unit/property/contract regression
  command - `501 passed`.
- Disposable PostgreSQL 18.4 migration plus Stage-7/8/9 integration command -
  `46 passed`; named container `dmf-pulse-gw1-24-postgres` was stopped and
  auto-removed.
- Frozen Stage-9 resource assurance - `PASS`.
- Ruff format - `PASS`, `527 files`; Ruff lint - `PASS`.
- Strict mypy - `PASS`, `204 source files`.
- Source/wheel build - `PASS`, `dmf-pulse 0.2.0`.
- Installed-wheel public current-points import outside the source tree -
  `PASS`; installed `dmf --help` - `PASS`. The first disposable CLI attempt
  inherited an incompatible global Typer; the accepted smoke used the frozen
  project dependency set while asserting `dmf_pulse` loaded from the installed
  wheel location.
- First-party secret scan - `PASS`, `finding_count=0`.
- Workflow YAML, schema reproduction and `git diff --check` - `PASS` before
  capability freeze.
- Repository validation was deferred at the bounded checkpoint; the final GW1
  gate regenerated GCS-008 and the active EVAL-012 current manifest and passed
  with zero errors.

## Status before final remote attestation

- Local bounded engineering result - `PASS`.
- Linux engineering result - `PENDING_FINAL_PUBLICATION`.
- Checkpoint 2.4 engineering capability - `LOCAL_COMPLETE / FINAL_REMOTE_PENDING`.
- Current operator projection - `BLOCKED_CURRENT_EVENT_PRIOR_ARTIFACT`.
- PR, merge and production activation - `NOT_AUTHORIZED / NOT_PERFORMED`.

## Historical pre-remediation capability hashes (superseded)

The following hashes describe the earlier local capability before the
clean-checkout remediation and final programme delta. They are retained only as
historical evidence and are not final-tree identities.

- `src/dmf_pulse/fpl_points/current_points.py` -
  `c8c713071fb00ffb117eab6ee9343bb689fb69511337304c04f666bc05478853`.
- `src/dmf_pulse/fpl_points/models.py` -
  `faa13d47befc37a2fcb866d5bc6d4e833768164b373846f116c72d342f527213`.
- `src/dmf_pulse/fpl_points/rules_adapter.py` -
  `1b3a769ce23737bacbaa23a83f1e2f04bb0b9bb78471a14edebfc7c77e716bb1`.
- `src/dmf_pulse/availability/current.py` -
  `2b18f29929facf8984b469594001d700eba4a069c7133ea2092833b89e762004`.
- `src/dmf_pulse/fpl_points/__init__.py` -
  `0eec67478c75c5523c7422ac916d944dfa1f939a7219923510f2edc526ea1372`.
- `tests/unit/fpl_points/test_current_fpl_points.py` -
  `4a9917564507cac808a50338218987cc704d4a1171b210b4632bbfcf99203f7b`.
- `fixtures/points/PTS-009/manifest.json` -
  `dbf9173e19e865dab6f36ea755b0fef8d57aebc280489a86d5ec7a56bf20c930`.
- `fixtures/points/PTS-009/schemas/fixture_request.schema.json` -
  `13b0625da219453f2d59e2a5906a059edd0f9854b73c537da0620d904d65a719`.
- `fixtures/points/PTS-009/schemas/fixture_result.schema.json` -
  `b5e27ab29cfe23b9376bbe91a8d386bfe1087380132b3c481beed949fab00652`.
- `.github/workflows/gw1-checkpoint-2-4-validation.yml` -
  `dfab30fad0699a51076b8c8af352d1e45004a89d87b043898a1e5343cefc42ee`.
