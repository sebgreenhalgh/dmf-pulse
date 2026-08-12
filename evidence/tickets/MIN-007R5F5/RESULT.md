# MIN-007R5F5 result

PASS. Final-output publication no longer executes a transaction-wide constraint-mode change. It validates only the final-output constraint trigger for immediate feedback and restores that named trigger to deferred mode. The unrelated deferred scenario graph remains composable.

The mandatory one-outer-transaction regression publishes valid complete A, then valid complete B through its normal deferred scenario/member construction, and commits with both final outputs readable and complete. R5F4 truthfulness, direct-SQL enforcement, post-complete freeze, and COMPLETE-only lookup remain passing. Frozen identities and Alembic head `20260807_0006` are unchanged.

All 22 literal acceptance commands passed. Docker was torn down. The exact commit is recorded after this evidence is committed.
