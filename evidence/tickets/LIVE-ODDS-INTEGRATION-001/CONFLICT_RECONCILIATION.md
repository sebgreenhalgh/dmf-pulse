# LIVE-ODDS-INTEGRATION-001 conflict reconciliation

## Observed merge

The exact merge of accepted commit `5e55cf3361a1abff4b2e32dcc30fe42900ea2e16` into first parent
`fceca02d21ec7031e36518c46724c6a6d3d6c72e` produced exactly:

1. `PLANS.md` — one modify/modify content conflict at the common top insertion anchor.
2. `evidence/tickets/PRC-013/current_manifest.json` — one modify/modify content conflict in the
   generated `PLANS.md` record.

There were zero executable conflicts and no conflict under `src/`, `config/`, `tests/`, `scripts/`,
or `.github/`.

## PLANS policy

The repaired-main 121-line programme block remains first and exact. The accepted LIVE-ODDS 41-line
production block remains second and exact. Both precede the shared CHIP-014 history. The accepted
LIVE-ODDS independent-review remediation tail and all shared history remain exact. No checkpoint or
historical prose is rewritten.

## Active manifest policy

The PRC-013 manifest is mutable whole-tree governance state. It is regenerated only after the
combined PLANS resolution and this ticket namespace exist, using the canonical repository
generator. Parent selection, manual JSON splicing, and historical manifest regeneration are absent.

## Acceptance separation

Human acceptance of LIVE-ODDS remains bound to `5e55cf...`. It does not accept the integration merge.
Independent integration review and human integration acceptance remain pending.
