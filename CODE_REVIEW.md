# DMF Pulse review standard

Review FND-001 in this order:

1. Scope and authority: approved hashes/statuses, zero-cost DMFP-04, and no future-domain code.
2. Configuration and secrets: strict models, reference-only credentials, deterministic redaction, and no leak in errors.
3. Packaging: canonical version, `py.typed`, import purity, and proof from a clean wheel outside the source tree.
4. Portability/processes: Windows/POSIX paths, explicit boundaries, timeout/truncation, cleanup, and healthy GPU absence.
5. Evidence/review integrity: canonical hashes, exact failures, baseline diff, detached review manifest, and 20-file cap.
6. Test strength: negative paths, independent oracles, golden contracts, property tests, and false-success prevention.
7. Supply chain: approved direct dependencies only, exact uv lock, package contents/hash, and honest licence metadata.
8. CI: frozen commands, least privilege, no production secret, and local parity.

P0/P1 findings block Codex completion. Passing tests alone is not acceptance, and human approval remains required before merge/tag.
