# R8A-R1 governance candidate

Parent: b258c6e9c560ff0dd1e6f358f7fe3f74610e1578.
Parent CI 34639186932 was independently rechecked: exact SHA, all 12 jobs success.
New candidate review/publication/CI are pending at this evidence snapshot;
the final handoff must report those separately, without rewriting this snapshot.

## Scope and authority

Human authority and exact supplied timestamps are transcribed in
`tickets/PRIVATE-V1-ONE-COMMAND-001N-R8A-R1/HUMAN-APPROVAL.md`.
Initial timestamp STOP was honored. Resume uses actual human-supplied review
completion and reaffirmation, not implementation time or date normalization.

Only live Odds-profile fields account_scope, approved_at, approved_by,
approved_purpose, checked_at, geography_scope, human_approval_id, notes and
terms_version change. All capability bytes and unresolved-rights values remain
unchanged, as do the complete synthetic profile and every other provider setting.
The scoped R8A operation does not reinterpret unrelated provider capabilities.

Full src/ and scripts/ trees, FPL rights, provider configs, dependencies, CI and
historical R8A ticket/evidence are byte-identical to the parent. No source/model/
decision algorithm changed. The expected authority/configuration hashes DO change.
No frozen artifact or historical expected hash was rewritten.

## Hash lineage

Canonical Odds rights registry:
- before: 8a73cd29c0ed89c1edc66953de26a1f9af6c778c18cad8621ffd1ce357a1205c
- after: d5b21c0917286053245e595bc9337ca9de8dec9f056bcfef2c655f372f394f63

Effective provider/rights configuration:
- before: b87b72f72b493ed8dd83babe5cb1cdcc98b184b5de51437dd4df38158353feb9
- after: cb6a091a977c8fac3c6674bedb31947ee99ea4f92a791c48cffd644d33c80baa

Raw canonical Odds rights file SHA256:
- before: 59211cf23b3d9439fd43d61034eabd96677b2246ece43ae44027e7a8c04e0945
- after: a60d541e683c3e5a10e3b9504313ca9ac2a6fcf5650cfda2d4cd7ca8e2d9331c

Search of current tests/fixtures/config/scripts found no literal expectation of
the old canonical rights/effective/raw hashes needing an update. Dynamically
derived lineage changes legitimately. Historical hash-bound artifacts remain
historical; package-build identity can also change without algorithm changes.

## Local acceptance

- Complete offline ingestion unit suite: 1,137 PASS before three additional
  schema-removal cases; final focused suite: 99 PASS (83 R8A + 16 governance).
- Frozen sync: PASS, 40 packages, no lock/dependency changes.
- Ruff format/check: PASS, 790 Python files formatted; strict mypy: PASS,
  286 production files. Specs: PASS, 94 decisions/22 documents/19 scopes.
- Build: PASS, wheel and sdist 0.2.0.
- Clean external installed wheel: PASS; native load_rights_profiles sees exact
  human approval, account/geography/purpose/timestamps and unchanged gate passes.
  Resource SHA equals the canonical source file. Frozen requirements are exported
  with hashes and synced offline; wheel installed offline with no dependency
  resolution. Isolated Python cannot import repository package source. The
  unchanged standalone operator script is file-loaded without invoking main.
- Manifest integration: 4 PASS; canonical PRC-013 and R8A-R1 manifests generated
  with 1,372 repository deliverables each. Historical R8A manifest preserved.
- Repository validator: zero errors; secret scan: zero findings; diff check PASS.
- Whole-repository branch coverage and remaining mandatory gates are delegated
  to required exact-SHA CI, not claimed from the focused local results.

No live probe, FPL/Odds request, runtime credential inspection, model invocation,
R8B, PR, merge, tag or activation. No provider material in evidence.
NO PREMIER LEAGUE PERMISSION CLAIM; NO NEW FPL LICENCE CLAIM; NO FPL RIGHTS EXPANSION.
