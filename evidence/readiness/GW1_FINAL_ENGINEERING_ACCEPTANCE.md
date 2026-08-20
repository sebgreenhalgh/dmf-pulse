# GW1 2026/27 final engineering acceptance

## Identity and boundary

- Canonical branch - `readiness/GW1-2026-27-live-input-initial-squad`.
- Immutable programme parent - `9eb57143f6ee92f67c78607cc386678d962e62d4`.
- Resume SHA - `5838bc6b1a44070261035c2d3d53b9a77d9d4a3c`.
- Final SHA / Linux workflows - `PENDING_FINAL_PUBLICATION`.
- PR, merge, global rules activation, real provider call and FPL account action -
  `NOT_PERFORMED / NOT_AUTHORIZED`.

## Hostile review findings

### P0

None found.

### P1 - remediated

1. Checkpoint-2.4 Linux depended on an ignored developer rules artifact. Tests
   now compile and verify tracked authority in a temporary directory; workflow
   filters watch source/compiler paths.
2. Preseason Stage 10 had no legitimate target manager-tactics route and its
   1,000-scenario unfactorized cross-product exceeded the resource policy. The
   exact target GW1 capability and algebraically exact preseason factorization
   resolve both without weakening production.
3. Projection acceptance could silently omit an official player on an
   unprojected team. Missing/colliding players now block explicitly.
4. The first CLI draft could spend a live provider request before discovering
   invalid local rules/policy/prior/commit inputs. Those checks now run first.
5. A successful decision could have received a receipt after the GW1 deadline.
   Receipt time is now taken after Stage 10 and compared with the official
   deadline before any write.
6. Eager optimisation package exports created an import-order cycle when rules
   loaded first. The unnecessary eager exports were removed and clean-process
   import order is covered.

### P2 - remediated

- Prospective construction initially normalized naive timestamps and compared
  existing receipt hashes rather than exact bytes. It now rejects naive times
  and permits idempotency only for byte-identical content.
- The final Linux workflow initially selected database-backed security tests
  without PostgreSQL. It now provisions the exact pinned 18.4 image, migrates to
  head, and supplies only the test database reference/fake password.
- The first final Linux publication (run `32355035128`; `411 passed, 6 failed`)
  exposed five terminal-width-dependent CLI assertions and one assurance
  fixture whose purportedly invalid one-player reduced candidate was valid by
  contract. The artifact test now uses duplicate IDs, preserving reduced exact
  oracle cases. Replacement run `32358512801` confirmed that correction
  (`412 passed, 5 failed`) and proved Click's `terminal_width` did not control
  Rich's table width on Ubuntu. Run `32360301030` (`412 passed, 5 failed`)
  further proved invocation-scoped `COLUMNS` was too late because Typer caches
  width at import and GitHub forces ANSI rendering. Error tests now patch the
  pinned Typer width before rendering and strip ANSI; the GW1 option-surface
  test inspects registered command metadata instead of visual help layout. All
  31 affected-file cases pass with `GITHUB_ACTIONS=true` and a forced 20-column
  outer terminal.

### P3 / retained limitations

- Stage 7 is an explicit current-history cold start using frozen synthetic
  TEST/REPLAY training evidence; no production-calibration claim is made.
- The event prior is external governed operator input; no accepted real current
  artifact was supplied during engineering.
- Three candidate pools are heuristic and distinct; Stage-10 tactics are exact
  inside each pool, with no broader global-optimum claim.
- A complete unsharded Stage-6-through-12 command reached a 20-minute local
  resource limit with no failure output. The complete repository pytest attempt
  was terminated after more than 30 minutes with no summary and is recorded as
  `RESOURCE_LIMIT`, not PASS.

No unresolved P0/P1 or material P2 finding remains before final Linux execution.

## Local final validation

- Current Stage 6-9 plus Stage 12/orchestration/CLI - `160 passed` in `533.26s`.
- One-Gameweek Stage 10 inherited/new suite - `43 passed` in `681.17s`.
- Rules/rights/security non-database cases observed - `198 passed`; the same
  command's 10 PostgreSQL cases correctly refused missing setup, then passed in
  the configured database gate below.
- PostgreSQL 18.4 migrations plus security and Stage-7/8/9 integrations -
  `63 passed` in `151.88s`; disposable container/network/volume removed.
- Current Stage-7/8/9 branch coverage - `34 passed`, `92.27%` across `1,107`
  statements / `200` branches (`93%`, `90%`, `93%` by module).
- Frozen Stage-9 resources - `PASS`.
- Ruff format - `PASS`, `527 files`; Ruff lint - `PASS`.
- Strict mypy - `PASS`, `204 source files`.
- Wheel and sdist build - `PASS`, version `0.2.0`.
- Installed-wheel isolated import/version/GW1 help - `PASS`; temporary
  environment removed.
- First-party secret scan - `PASS`, zero findings.
- Git whitespace assurance - `PASS`.
- Repository manifest/validation - `PASS` after deterministic final GCS-008 and
  active EVAL-012 current-manifest regeneration (`0` validation errors).
- Complete repository pytest - `RESOURCE_LIMIT` after the explicit ceiling; no
  completed pytest summary is claimed.

## Engineering status before publication

`LOCAL_ENGINEERING_COMPLETE / FINAL_REMOTE_PENDING / OPERATOR_LIVE_RUN_PENDING`

The desired final state becomes
`GW1_ENGINEERING_READY_FOR_OPERATOR_LIVE_RUN` only after both exact-SHA Linux
workflows pass and local/remote equality is verified. This is not a real GW1
decision and does not remove the event-prior/current-data/operator checkpoints.
