# CURRENT-AVAILABILITY-001B implementation plan

- Bind all work to immutable parent `99418f3316277f4dae347d80358d5dd5a09655b2` only after
  parent CI run `33401091116` concludes successfully.
- Preserve the dirty CURRENT-AVAILABILITY-001A worktree read-only and port only its valid
  identity, cutoff, semantic-hash, hard-evidence, and private/transient concepts.
- Define a strict fixture-scoped private manual contract with explicit provenance and positive
  integer scenario counts totaling exactly 256 for each team.
- Reuse the accepted Stage-7 lineup and projection contracts to derive exact role probabilities,
  91-bin minute PMFs, deterministic scenario/result hashes, and grade-D confidence.
- Extend the closed Stage-7/Stage-8 model-family boundary only with
  `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1`, preserving every existing identity and cutoff gate.
- Provide one immutable private CLI surface and synthetic Stage-8 integration proof.
- Run focused branch coverage, affected regressions, all database/migration tests, static checks,
  build, installed-wheel, repository-manifest, secret, and exact-SHA CI gates.
- Stop pending independent review. Do not create a PR, merge, tag, record human acceptance, or
  activate production.

All implementation steps above are engineering-complete. Exact final-SHA CI remains a post-push
gate and is deliberately not claimed by this pre-push evidence file.
