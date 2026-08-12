# MIN-007R5F5 evidence plan

- Parent: `94b561f427e18e6200acb892d44b99e1038a70eb`.
- Scope: remove the transaction-wide constraint-mode leak from final-output publication.
- Implementation: validate only `trg_min007f_final_output_complete` immediately, then restore it to deferred; leave unrelated graph constraints deferred.
- Regression: publish valid complete A and B, including B's deferred scenario/member construction, in one outer transaction and commit successfully.
- Exclusions: no migration, schema, formula, CLI, provider, or future MIN-007H work.
