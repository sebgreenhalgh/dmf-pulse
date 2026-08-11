# MIN-007R5F2 plan

Close only AUDIT-007-3 findings 6–8: canonical one-based PostgreSQL PMF arrays
with exact HALF_EVEN derived projection checks, scenario/final cross-graph
coherence, and strict model-bound evaluation persistence. Modify unmerged
`20260807_0006` and matching SQLAlchemy metadata only; preserve R5F1 behavior and
all frozen F/G identities.

Validation covers focused public-identity, relational/numeric, and evaluation
regressions; inherited F/G/R5F1 tests; migration reversibility; the frozen G
oracle; all 23 acceptance commands; and final teardown/clean-tree checks.
