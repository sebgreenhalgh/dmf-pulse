# CI-TEST-002 lineage reseal

Status: `RESEALED_PENDING_INDEPENDENT_LINEAGE_CONFIRMATION`.

## Historical reviewed boundary

- Original parent: `d550250836c9c39e6caebaa5f12ad94fec7e2b02`.
- Original reviewed head: `840b6b7150808f19a3c32171aea6846e55fa8554`.
- Independent verdict: `REVIEW_CLEAN_PENDING_EXTERNAL_CI_GATE`.
- Reviewed executable: `tests/contract/evaluation/test_cli_contract.py`.
- Reviewed blob: `1141bfb59b94901973241bede6f8cb601c63e0d9`.
- Reviewed stable patch ID: `318e4f84282bc5ed73a3270a8c1571aff81f8742`.

## Rebuilt boundary

- New parent: `af78cedc65bd043343825facae947b8aed5340a4`.
- Rebuild branch: `rebuild/post-A-FPL-001-correctness-stack`.
- New rebuilt head: the direct-child commit containing this record; its exact local/remote SHA is
  reported after commit and the single push because a commit cannot contain its own object ID.
- Rebuilt executable blob: `1141bfb59b94901973241bede6f8cb601c63e0d9`.
- Rebuilt stable patch ID: `318e4f84282bc5ed73a3270a8c1571aff81f8742`.
- Blob identity: `IDENTICAL`.
- Substantive patch identity: `IDENTICAL`.

The upstream A-FPL remediation required mechanical stack reconstruction. No semantic
implementation, diagnostic observer, workflow, timeout, dependency, runtime configuration, or
production change is introduced.
