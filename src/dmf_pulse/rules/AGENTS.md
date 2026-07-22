# Rules package constraints

- Compile policy from validated split YAML; scorer code contains algorithms, never season constants.
- Keep scoring and aggregation pure: no I/O, subprocess, environment, clock, network, or database access.
- Bind every result to an explicit ruleset ID/version/hash. Do not add a mutable `latest` resolver.
- Unknown or conflicted required values fail closed for scoring and activation.
- Preserve generic competition ranking and configured interval/group boundaries; do not branch on fixture IDs or expected outputs.
- Target-season changes require cited source references and full lifecycle approval. Never fill an unknown from memory.
