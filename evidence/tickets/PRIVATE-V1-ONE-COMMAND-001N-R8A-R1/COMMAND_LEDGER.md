# R8A-R1 command ledger

All commands run in the isolated R8A-R1 worktree. No provider execution or
credential inspection. Root worktree's unrelated availability edits untouched.

- Previous turn: parent Git object and gh run view 34639186932 verified; read
  rights schema/authority; stopped before edits because date-only approval had
  no documented datetime convention. Resume read supplied exact timestamps.
- git worktree add -b readiness/PRIVATE-V1-ONE-COMMAND-001N-R8A-R1-rights-approval-reconciliation
  review_pack/one-command-n-r8a-r1 b258c6e9c560ff0dd1e6f358f7fe3f74610e1578: PASS.
- uv sync --all-groups --frozen: PASS.
- uv run pytest tests/unit/ingestion/test_horizon_rights_approval.py -q --tb=short:
  RED before registry update, 9 expected failures/4 passes. Initial guard also
  blocked pytest's environment-based failure formatting; confined guard to the
  function under test, then obtained the clean RED result above.
- Metadata updated. Two R8A stale-profile tests now explicitly synthesize the
  old metadata instead of assuming that the mutable registry stays pending.
  No gate behavior/assertion weakened.
- uv run pytest tests/unit/ingestion -q --tb=short: 1,137 PASS, 156.67 seconds.
- Added three missing-capability schema cases, then:
  uv run pytest tests/unit/ingestion/test_horizon_rights_approval.py
  tests/unit/ingestion/test_horizon_probe.py -q --tb=short: 99 PASS, 3.01 seconds.
- uv run ruff format --check .; uv run ruff check .: PASS.
- uv run mypy src/dmf_pulse: PASS, 286 files.
- uv build --no-build-isolation: PASS.
- uv run python evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R8A-R1/verify_installed_authority.py:
  PASS, external native wheel resource equals canonical bytes, updated authority
  passes gate, provider_requests=0, credential_inspections=0.
- uv run dmf specs validate: PASS.
- uv run python scripts/generate_repository_manifest.py --ticket PRC-013;
  uv run python scripts/generate_repository_manifest.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R8A-R1:
  PASS, 1,372 entries each. Evidence excluded by canonical generator.
- uv run pytest tests/integration/repository/test_manifests.py -q --tb=short:
  4 PASS, 1.87 seconds.
- uv run python scripts/validate_repository.py: zero errors.
- uv run python scripts/scan_secrets.py: zero findings.
- git diff --check: PASS.
- git diff --exit-code b258c6e9c560ff0dd1e6f358f7fe3f74610e1578 -- src scripts
  config/rights/fpl_profiles.json config/providers pyproject.toml uv.lock .github
  tickets/PRIVATE-V1-ONE-COMMAND-001N-R8A evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R8A:
  PASS (byte-identical protected surfaces).
- Read-only Python Git/config audit: exactly nine approval metadata fields differ;
  capability byte slice identical, synthetic profile and unresolved rights equal.
  Initial shell quoting error rerun successfully; no file mutation from audit.

Independent review and exact-SHA CI results belong to final handoff after this
snapshot. No parent CI result is represented as descendant CI.

- Final focused plus manifest repeat: 103 PASS, 4.81 seconds.
- uv run python scripts/build_review_pack.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R8A-R1
  --baseline b258c6e9c560ff0dd1e6f358f7fe3f74610e1578
  --output review_pack/r8a-r1/canonical-review-check:
  REVIEW_TICKET_UNSUPPORTED (no installed ticket review-pack contract).
  No canonical acceptance certificate claimed. A supplementary exact-commit
  archive may be built with the existing ReviewEntry/enforce_review_limit cap;
  its hash and binding are reported separately at handoff, not as a certificate.
