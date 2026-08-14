# Football-events module instructions

## Scope

This package owns GCS-008 team score and clean-sheet distributions only. The canonical output is one joint home/away score matrix and its deterministic team-level derivations.

## Frozen upstream boundaries

- Stage 6 normalized market consensus is authoritative for accepted market semantics and identities.
- Stage 7 availability/start/minutes mathematics, identities, persistence, packaged replay resources, migrations, CLI, and assurance are frozen.
- Consume Stage 7 through `Stage7MinutesContext`; never import player PMFs into new Stage-8 mathematics or mutate Stage-7 artifacts.
- Stage-7 context is cutoff-safe only when both accepted team identities match the fixture and teams, share one source cutoff, and are no later than the Stage-8 information cutoff.

## Numerical rules

- Use exact `Decimal`; reject binary floats, booleans at decimal boundaries, NaN, and Infinity.
- Public probabilities are 12-place strings and exact simplexes.
- Public expected values and scoring measures are 6-place strings.
- Keep pure mathematical modules separate from orchestration and persistence.
- Maintain adaptive support, explicit omitted-tail diagnostics, deterministic solver behavior, and visible fallback status.
- Never derive team outcomes from a second model; derive all public views from the canonical score matrix.

## Identity and replay

- Bind policy, prior, Stage-6 evidence, full Stage-7 identity context, fixture/team IDs, and UTC cutoff into canonical SHA-256 identities.
- Public artifacts must be self-validating and content addressed.
- Existing different bytes at the same semantic artifact path are an error, not an overwrite.
- No live provider/network/database access in pure modules, TEST, REPLAY, golden, or property tests.

## Exclusions

Do not add player goal/assist allocation, shots, saves, cards, penalties, own goals, defensive events, match timelines, production bivariate Poisson, or Dixon–Coles under GCS-008.
