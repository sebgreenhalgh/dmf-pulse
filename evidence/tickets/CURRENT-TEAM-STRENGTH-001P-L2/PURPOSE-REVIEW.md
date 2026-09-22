# L2 purpose-only review

Controlling human instruction: Phase A only. The agent must not invoke `observe`.
Fresh reference and attestation are recorded in the ticket's HUMAN-APPROVAL.md.
This is an engineering scope/authority review, not a new provider licence,
provider endorsement or legal opinion. No credentials were inspected.

Authority resolution used `specs/manifests/authority_manifest.json`, approved
DMFP-20 ADR-GOV-001/002/004, ADR-DATA-004/007 and ADR-SRC-001/002/003/004,
DMFP-05 sections 26.1/26.9, DMFP-04 private source-rights boundaries, the exact
standing provider profiles, P0 governance, and the accepted D1 parent contracts.
An independent purpose/design reviewer found no genuine authority conflict.

## Official FPL: no amendment

`fpl_official_private_operator_initiated_read_v1` covers the existing one-entry,
low-volume, operator-initiated read-only frozen-state acquisition for private
analysis. The sequential acquisition and memory-only preparation are unchanged.
Standing FPL purpose, geography, account scope and capabilities are not broadened.

Raw configuration SHA256:
`1691229b120054b8d4c65c7d74e5a0f6d9d11947f1a8f261d26649314268011d`.
Pinned private-profile semantic SHA256:
`f319842091b89b0f8cc207b681d2584e1cce282e570d5d4daba92b06ae85f095`.

## Odds: exact L2 purpose only

Only `approved_at`, `approved_purpose`, `human_approval_id` and `notes` change
from parent `4d712ecf84e9c1f01a0f29354bd93c5296befb35` in the existing
`the_odds_api_private_analytics_v1` profile. The measured capture timestamp is
2026-09-22T19:07:31Z; it is not asserted to be the human message's send time.
All other fields remain equal, including version, Sebastian-owned account,
United Kingdom geography, terms metadata, capability matrix, unresolved rights,
zero retention and deletion requirement. Public display and redistribution stay
DENY. Synthetic rights are unchanged.

New exact semantic SHA256:
`bc5dfa98500459bc50c00e4cd44a30e64e0df04957f383ec8107947ac5350faf`.
The validator pins it; any subsequent purpose or capability drift fails closed.

## Consumption, public readiness and activation

The literal historical L1 approval stays in a frozen consumed set and is rejected
before current-pair checks or credentials. Only the exact fresh L2 pair validates.
No general-purpose selector, reset or automatic retry is introduced. Existing
first-private-transport consumption and process-local closed-network guard are
unchanged. This is not a durable cross-process L2 ledger: the human must invoke
once and never rerun after any private request under this approval.

OpenFootball authority and P0 freshness remain byte-identical. Public stale,
unavailable, incomplete or invalid readiness blocks before private access.
The standing FPL and exact Odds profiles are checked independently. No private
material can enter fitting, persistence, review archives or CI. Ordinary league
selection, D1 semantics and Stage 8-11 mathematics are unchanged. Team strength
remains SHADOW_NOT_MODEL_INPUT; 001U/mixtures and production activation are absent.
