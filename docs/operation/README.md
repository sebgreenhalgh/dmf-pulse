# Operations and active research

Active research is `research/DMF-MODEL-QUALITY-001`, checked out in
`review_pack/MODEL-QUALITY-001`. Required launch operation remains in
`review_pack/GW10-LAUNCH`; the separate availability checkout is protected.

Start with the [consolidated cleanup, feedback and model-quality report](QUALITY-CLEANUP-ACCELERATION.md).
It records actual archive boundaries, performance, source/privacy controls,
independent review and remaining exact-commit acceptance gates.

- [Current model audit](MODEL-QUALITY-001-CURRENT.md)
- [Validation scorecard and missing real labels](MODEL-QUALITY-001-VALIDATION.md)
- [Prioritized research roadmap](MODEL-QUALITY-001-ROADMAP.md)
- [Research v2 analytical dictionary](ANALYSIS-DICTIONARY-v2.md)
- [Continuation acceptance](../../tickets/DMF-MODEL-QUALITY-001/RESUME-ACCEPTANCE.md)

For local edits use `uv run --frozen python scripts/dev_checks.py fast --target <test-path>`.
`focused` and `integration` add the applicable subsystem targets;
`full --ci-run <id>` verifies every mandatory exact-HEAD job. Partial feedback
does not promote a model or replace production release acceptance.
