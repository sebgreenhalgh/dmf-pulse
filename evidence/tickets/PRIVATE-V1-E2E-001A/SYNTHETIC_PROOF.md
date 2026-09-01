# Deterministic synthetic full-stack and installed-wheel proof

This proof is explicitly `REPOSITORY_OWNED_SYNTHETIC`, TEST-only, and not a real private
recommendation. It uses season 2026/27 GW1 solely because the packaged candidate allocation prior
is hard-scoped to GW1.

## Safe run identity

- Run: `PRIVATE_V1_SYNTHETIC_E2E`.
- Cutoff: `2026-08-21T17:30:00Z`.
- Root seed: `1729`; Gameweek scenarios: `1`.
- Execution input: `972c175988c312f8a4cc6a7dbcd463671e5843f00b2766def566f93370b09703`.
- Current state: `a7659767c6ef1b9e83a7cb8d5c2baef96572c2493ae97ec6db19dfb54a2c5453`.
- FPL input: `66b6607907532336f0c4e5bd4e860ba7f70925266f8b0fd689d5aa7d265e6402`.
- Odds market: `5276c4eccf4f6477793cafe15e82265ab0a6a1ac7ee103e8f4fab696352f1970`.
- Market constraints: `1aa97f43a645649cf8ef70ce8a1e137ecf714b2e73cf4805b1c3dd93848b8739`.
- Stage-8 policy: `56c21c9fc6cdd00d5e7cfd79d491e0c1fcc14a16b67adf5d455612c1a8be3431`.
- Stage-9 MC policy: `f42467ef59c8aa20dc6089866527fc5c3eaa6e8fd2a8cc119322dfa4411f84cb`.
- Player-allocation config: `c81e5498ca243836f6aec4152daa5722915c89c9f5d32704240e96751bdcbbea`.
- Player prior: `629d6c288f9faa7aa7763f5c578e662511c03d514169f683cbeb6ee81af695be`.
- Historical acceptance record: `39737c6b96e2664f63f19b4ea0c34038d7c0ec5d9afc9f60cc1c6b89749a3352`.
- Stage-9 result: `f21dfe4df09ef960962d935fe081a4e427570e3d34feb0844f9333c55148cba9`.
- Joint matrix: `5583a846e235cbc5d42b3ad1cfea1254cfd328c50c2d00a059a51d8622d72221`.
- Stage-11 request/result: `b5684ebacad0b53ff206c9d916dd3e3bbd6d799b94a3278ad89f2b2afe81c4f7` /
  `00de2c300121e233b2ff9818e35654cf6b73bdea7fd034061e80b81d2fe91d7e`.
- Decision: `a51391ad37f89b54281c3fdab1fd07cc9c9860aba14facfa8ab51230a36fa2d8`.
- Replay manifest: `a4b1c8e2a55fb361bc87481e156641151035bddc6d7730e101334f46c95c187d`.

## Synthetic decision

- Action: `NO TRANSFER`; hit: `0`.
- Resulting squad: 15 unique players; position counts 2 GK, 5 DEF, 5 MID, 3 FWD; club limit at
  most 3; nonnegative bank.
- XI: 11 unique players; formation `5-4-1`; one starting goalkeeper.
- Bench order: goalkeeper `ce4ab141-d293-5c59-8131-ee194678761f`, then
  `a2e5445d-aeda-5267-9154-1fb418426bc4`,
  `d87e9192-7697-577c-a0bf-f77e739dc7fe`,
  `e6905f26-859b-5738-a917-de34d4d3b29c`.
- Captain: `6706a2b4-0840-5c52-b247-cb185c3ed9f3`; vice:
  `f8859d5f-7fe4-5364-b961-ee13cbfae051`; multiplier applied once.
- Recommended before/after hit: `33.00` / `33.00`; no-action: `33.00`; net uplift: `0.00`;
  paired p10/median/p90: `0/0/0`; outperformance probability: `0%`.
- Stage 7: `PRIVATE_MANUAL_TRANSIENT_OVERRIDE_V1`, LOW, NOT_MODEL_DERIVED.
- Stage 9 MC status: PASS. Chip action: `NO_CHIP`.

## Replay proofs

The current service test performed source execution, atomic freeze, exact service replay,
relocation, byte tamper rejection, and unexpected-file rejection. The dedicated wheel proof then:

1. built `dmf_pulse-0.2.0-py3-none-any.whl` with SHA-256
   `f20bc9f13cc0212312d4c05f65083712270c0b7599fde81299c8e08541e125b7d`;
2. installed it in a temporary environment outside the repository with the exact frozen runtime
   distributions;
3. verified `dmf_pulse` imported from that environment's `site-packages`;
4. installed a process-local guard that raises for DNS and socket connection attempts; and
5. ran `dmf private-v1 replay --bundle <relocated-bundle>` successfully, reproducing the exact
   manifest above.

The general clean wheel verifier also passed with network fetch disabled, exact locked runtime
inventory, `dmf 0.2.0`, healthy PostgreSQL doctor, schema/demo/as-of checks, packaged timezone,
and cleanup. Its sdist SHA-256 was
`bf38e855b888e16dbdc2c9c760ee665e60fe6010913299d2820309ca8abdeb6d`.
