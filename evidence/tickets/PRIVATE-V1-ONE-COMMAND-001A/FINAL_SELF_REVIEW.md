# Adversarial self-review

| Attack | Finding and disposition |
|---|---|
| Official-FPL write capability | None. The closed transport accepts only GET and allowlisted paths; no write surface exists. |
| Bearer/password leak | No password path exists. Token input is environment or hidden prompt only; request and credential representations redact headers/secrets. |
| Provider response persistence | No file, database, cache, backup or replay boundary is called; provider bytes are released after parsing. |
| Stale public picks used as current | No. Authenticated `/my-team/` is mandatory for current state and public picks are used only for ownership lineage. |
| Wrong or expired target GW | Deadline and current/next flag checks fail closed; the target is not hardcoded. |
| Missing live minutes treated as zero | No. Missing minutes/starts remain `None` and are omitted from factual history. |
| Ad-hoc Stage 7 | No. The accepted regularised empirical-Bayes/coherence family and shrinkage resources are invoked. |
| Hidden fuzzy mapping | No. Mapping uses exact reviewed aliases, fixture side, kickoff and provider identity; ambiguity blocks. |
| Tiny hand shortlist | No. The policy contains every provider-selectable non-squad player; the declared current-V1 action horizon is one transfer. |
| Stale prior described as current | No. Original cutoff, grade E, historical GW1 acceptance and explicit current-GW carry-forward warnings remain visible. |
| Scorer/optimiser/captain duplication | None. Existing Stage 8-11 and captaincy boundaries are called. Exact Stage-10 evaluation was factored to remove repeated autosub work without changing its search space or proof counts. |
| Comparator/captain mismatch | Existing aligned-scenario comparator and independent captain verification remain mandatory. |
| Synthetic result labelled real | The test uses injected provider-shaped transports; only the genuine command can emit the real status. |
| Excessive or concurrent FPL requests | Sequential only, 24-attempt run cap, three attempts per endpoint, pacing, Retry-After and finite timeouts. |

No unresolved P0/P1 finding remains. Exact-final-SHA CI, independent review and human acceptance
remain separate and are not claimed here.
