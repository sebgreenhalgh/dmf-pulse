# CURRENT-FPL-STATE-001B independent-review remediation

Reviewed deficient SHA: `d59a105669f271dfe0cfcb9b31b28becc922a11a`
Finding: `CFSB-REV-001`
Severity: material P2
Original push CI: `32991867645`

## RED reproduction

The bound `OddsProviderCurrentInput` contained only `Alpha Athletic` and `Beta Borough`. The
approved plan additionally contained `Gamma City -> FPL team 3`, although no supplied Odds event
used `Gamma City`.

At the deficient SHA, resolution succeeded. `CurrentTeamIdentityMap.team_mappings` and the final
`FplOddsIdentityMap.team_mappings` contained all three strings, and `team("Gamma City")` returned
team 3. The independently reproduced unobserved resolved set was `("Gamma City",)`.

## Root cause

The resolver expanded every approved plan alias and checked only that observed participants were a
subset of approved aliases. Nested model validation then required the resolved map to equal the
full plan, preserving the dormant alias as active current-decision authority.

## Fix

The remediation uses the minimal reject-extra policy:

1. Derive a sorted canonical participant set only from every supplied Odds event's exact home and
   away strings.
2. Require the plan provider-text set to equal that observed set before resolving any alias.
3. Embed the observed set in both typed resolved maps and include it in their semantic hashes.
4. Require nested plan, observed, and resolved sets to remain exactly equal.

The plan is operator-reviewed candidate authority until resolution proves exact current-source
coverage. The resolved team map is only the authority justified by the complete bound provider
population. The final fixture bridge becomes usable only after target coverage and all
outside-target ambiguity checks complete.

## Regression disposition

- Unobserved approved alias: blocked.
- All observed aliases: supported.
- Observed outside-target aliases: supported.
- Missing observed alias: blocked.
- Outside-target exact target collision: blocked as ambiguous.
- Two strings to one FPL team: blocked.
- Rehashed final dormant-map tamper: blocked by nested observed-set validation.
- Plan and provider order: deterministic.

Focused result: 68 team/fixture tests and 122 branch-aware tests passed. Aggregate focused coverage
is 90.4040404040404%. Relevant inherited non-database tests passed 530/530; the inherited
PostgreSQL population passed 92/92 through migration head `20260807_0006`.

## Final disposition

`CFSB-REV-001`: **CLOSED in remediation, pending fresh independent re-review**.

No human acceptance, PR, merge, production activation, or CURRENT-FPL-STATE-001C work is claimed.
