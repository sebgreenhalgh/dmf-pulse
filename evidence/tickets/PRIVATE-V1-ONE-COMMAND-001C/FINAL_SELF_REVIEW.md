# Adversarial self-review

| Attack | Finding and disposition |
|---|---|
| Broaden generic canonical semantics | Rejected. `assurance/canonical.py` is untouched; recursion is local to the FPL parser's two declared transformations. |
| Convert Decimal to float | Rejected. Nested fractional JSON remains `Decimal`; projection emits the existing exact normalized string. |
| Change frozen hashes | None. Existing bootstrap and fixtures semantic SHA-256 assertions pass unchanged. |
| Depend on mapping insertion order | None. Reordered nested dictionaries and equivalent Decimal text produce the same semantic hash. |
| Silently stringify arbitrary keys | Rejected. Both transformations fail closed on a non-string dictionary key. |
| Admit NaN or infinity | None. Nested `NaN`, `Infinity` and `-Infinity` remain malformed JSON under the existing parser policy. |
| Leave declared artifacts non-serializable | None. Nested dict/list/tuple Decimal and datetime paths serialize deterministically with `allow_nan=False`. |
| Alter unknown-field hashing | None. Model projection still excludes additive model extras and retains existing missingness behavior. |
| Credential or provider-body disclosure | None. Only byte counts, hashes, target GW, endpoint classes and typed errors were emitted; no body, entry ID or secret is retained. |
| Hide the next live defect | Rejected. The separate current-input Decimal rejection is recorded exactly and was not folded into this ticket. |
| Expand Odds or one-command architecture | None. No Odds, CLI, assembly, model, scorer, optimiser or report production file changed. |

Error-UX audit: expected parser/schema failures already retain `IngestionError` codes through the
one-command service, and the newly exposed current-input defect retains `INTERNAL_INVARIANT`
rather than collapsing to `ONE_COMMAND_INPUT_INVALID`. Introducing a new public error taxonomy or
wrapping every possible downstream Python exception would expand this narrow ticket, so no
additional UX production change was made.

No unresolved P0/P1 finding remains within the 001C parser-canonicalisation scope. The separate
current-input adapter defect, exact-final-SHA CI, independent review and human acceptance remain
explicitly separate and are not claimed here.
