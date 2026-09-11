# R8A-R1 acceptance

No live providers or credential inspection. One independent read-only review of
the complete final candidate is required before publication; no self-acceptance.

1. Verify immutable parent, isolated branch, source and historical evidence bytes.
2. Run `uv sync --all-groups --frozen`.
3. Run `uv run pytest tests/unit/ingestion -q --tb=short` (includes focused R8A,
   governed rights, configuration and current one-command rights boundaries).
4. Run `uv run ruff format --check .`, `uv run ruff check .`,
   `uv run mypy src/dmf_pulse`, and `uv build --no-build-isolation`.
5. Run `uv run python evidence/tickets/PRIVATE-V1-ONE-COMMAND-001N-R8A-R1/verify_installed_authority.py`.
   Require clean external installed-wheel loading, canonical packaged byte equality,
   exact approval metadata, eligible gate, zero network/credential access.
6. Run `uv run dmf specs validate`, and regenerate canonical manifests:
   `uv run python scripts/generate_repository_manifest.py --ticket PRC-013`;
   `uv run python scripts/generate_repository_manifest.py --ticket PRIVATE-V1-ONE-COMMAND-001N-R8A-R1`.
7. Run `uv run pytest tests/integration/repository/test_manifests.py -q --tb=short`,
   `uv run python scripts/validate_repository.py`,
   `uv run python scripts/scan_secrets.py`, and `git diff --check`.
8. Record before/after rights and effective hashes without rewriting frozen artifacts.
   Preserve capability values and unresolved rights. No production source edits.
9. Independent verdict CLEAR_FOR_PUSH_AND_EXACT_SHA_CI; remediate material findings.
10. Publish exact reviewed candidate; require all exact-SHA CI jobs successful,
    clean worktree and local/remote equality. No post-CI changes or live execution.
