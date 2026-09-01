# Private V1 live-transient operator runbook

`dmf private-v1 live-transient` is the only real-current execution surface in this milestone. It
uses manual official-FPL files, performs no official-FPL network or authenticated manager access,
and has no artifact-output or replay option.

## Before the command

Supply all of the following at one truthful common information cutoff:

- official-FPL `bootstrap-static` and `fixtures` JSON saved manually under the approved
  `fpl_official_private_manual_v1` process;
- a strict existing `CurrentManagerDeclaration` JSON, including the 15 player IDs, purchase and
  observed selling prices, bank, free transfers, lineup, captain/vice and complete chip tokens;
- an accepted `OddsProviderCurrentInput`, reviewed `CurrentTeamAliasPlan`, reviewed
  `CurrentFixtureMappingPlan`, and DAT-003 `CurrentMarketCanonicalIdentityView`;
- a DAT-003/operator `PrivateCanonicalPlayerIdentityMap`, a sealed `PrivateCurrentOwnership`, and
  a sealed `PrivateCandidateActionPolicy`;
- `{ "score_priors": [...] }` containing only fixture-bound `CURRENT_SCORE_PRIOR_BUNDLE` values;
- `{ "fixtures": [...] }` containing the complete `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1` inputs;
- the governed Stage-9 Monte Carlo policy file;
- for GW2 or later, `{ "policy_id":
  "PRIVATE_CURRENT_GW_STALE_PRIOR_CARRY_FORWARD_V1", "declared_at": "...Z",
  "assignments": [...] }`. Each assignment names a current official-FPL element ID and an
  explicit same-position governed fallback official-FPL element ID. An empty assignment list is
  valid only when every required player still has an exact same-team donor relationship.

Do not put credentials in any file or argument. Acquire current Odds and the current OpenFootball
score prior through their already-approved commands/mechanisms before this command. Do not replace
either with invented probabilities or a synthetic score prior.

## Execute

From an installed wheel, run the following as one command. The line is intentionally shell-neutral;
PowerShell and POSIX shells may wrap it visually without adding continuation syntax:

```text
dmf private-v1 live-transient --bootstrap <operator-bootstrap.json> --fixtures <operator-fixtures.json> --manager <operator-manager.json> --ruleset <verified-rules-directory-or-json> --rules-approval-reference <private-operator-reference> --rules-approved-at <RFC3339-UTC> --odds-input <accepted-current-odds.json> --team-alias-plan <reviewed-team-plan.json> --fixture-mapping-plan <reviewed-fixture-plan.json> --mapping-decided-at <RFC3339-UTC> --market-identity-view <dat003-market-view.json> --player-identity-map <dat003-player-map.json> --score-priors <current-score-priors.json> --stage7 <manual-stage7.json> --ownership <ownership.json> --candidate-policy <candidate-policy.json> --prior-fallbacks <current-gw-prior-fallbacks.json> --mc-policy <stage9-mc-policy.yaml> --gameweek <N> --captured-at <RFC3339-UTC> --information-cutoff <RFC3339-UTC> --run-id <PRIVATE-RUN-ID> --code-sha <40-hex-installed-commit> --root-seed <declared-seed> --scenario-count <declared-count>
```

Omit `--prior-fallbacks` only for GW1. The rules approval is sealed in memory against the compiled
VERIFIED ruleset and FULL_SEASON capability; it does not activate or modify either artifact.

## After display

A successful report starts with `TRANSIENT PRIVATE DECISION`, states
`NOT REPLAYABLE UNDER CURRENT RIGHTS PROFILE` and `NOT PRODUCTION ACTIVE`, and ends with a
zero-retention statement. The command creates no live input, decision, report, manifest, cache,
backup or replay file.

The three manual FPL/manager source files remain operator-owned because this command is not
authorized to destructively delete user files. Delete them promptly through the approved
operator process required by the rights profile. Shell redirection, terminal logging and screen
capture can themselves persist the displayed recommendation; do not use them for this command.
