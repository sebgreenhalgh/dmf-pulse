# R8A command ledger (synthetic engineering only)

- Read the supplied execution request, R8 research Markdown and source register.
  Broader R8B research instructions are not active implementation authority.
- Reverified parent SHA and gh run view 34619880451: all 12 exact-SHA jobs success.
- Created isolated worktree/branch at c60d5b34a7d8922cd274d1ef28648b9e6235d718.
- RED: uv run python -m pytest tests/unit/ingestion/test_horizon_probe.py -q --tb=short
  failed at missing horizon_probe module, before implementation.
- Initial fixture setup corrections: unique FPL fixture codes and consistent
  is_next/is_current flags; corrected synthetic OddsHttpResponse argument order.
- Corrected profile hashing to serialize immutable capabilities explicitly.
- Initial nine observation tests passed; expanded first set: 55 passed.
- Affected parser/client/identity/direct-FPL/one-command ingestion regressions:
  294 passed in 16.20 seconds (including the then-current focused tests).
- Synthetic end-to-end spies corrected to use existing CurrentScorePriorService.build;
  large payload parameter given a bounded test ID (no live material involved).
- Expanded focused suite: 81 passed in 4.79 seconds under branch coverage.
  Classifier 96%, operator script 98%, combined 97%; no coverage policy change.
- Rights gate additionally checks reviewed terms version date, not just approval date.

Final verification and independent review are still pending. No push, live request,
credentials inspection, model execution by the probe, or automatic observation export.
