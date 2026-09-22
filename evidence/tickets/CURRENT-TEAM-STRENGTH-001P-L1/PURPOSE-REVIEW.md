# Independent purpose review — 2026-09-22

Reviewer: independent read-only agent `/root/l1_rights_review` (Euler).
No provider execution, credential access or implementation edits were delegated.

Verdicts: FPL_PURPOSE_REVIEW_PASS; OPENFOOTBALL_PURPOSE_REVIEW_PASS;
ODDS_PURPOSE_APPROVAL_SUFFICIENT, conditional on exact machine authority update.
This is an engineering purpose review, not a new external legal/terms opinion.

- FPL: `config/rights/fpl_profiles.json:76–109`, standing
  `fpl_official_private_operator_initiated_read_v1`; low-volume operator-initiated
  read-only private recommendation, one operator entry, zero retention. The
  existing preparation/rolling pipeline falls within that private purpose.
  `tickets/PRIVATE-V1-ONE-COMMAND-001A/ACCEPTANCE.md:3–26` supplies the inherited
  acquisition and Stage-7/rolling scope. No FPL authority expansion is needed.
- OpenFootball: `config/rights/openfootball_profiles.json:39–71` already covers
  current EPL acquisition, source retention, dataset construction, fitting,
  model/covariance retention and private fixture priors. The semantic rights
  hash remains `b90075563647a69a87e201aa70fe6f44034828afd9ad3926decf5c45bb53b17c`.
- Odds: old R9C-A2 purpose cannot authorize L1. Human reference
  `DMF-CTS-001P-LIVE-RIGHTS-2026-09-22` must replace current purpose/approval
  metadata only. Account, geography, terms, capabilities, unresolved rights,
  retention and deletion remain exact. No provider permission is inferred.

Controlling architecture: DMFP-20 ADR-DATA-004/005/006 (lines 546–627);
DMFP-05 DO05-21 (206–208), 26.1 (2579–2596), 26.9 (2675–2685).

Required implementation conditions:

- First attempted FPL/Odds transport consumes the one-shot; public-only work does
  not. Disable inherited FPL/Odds automatic retries locally.
- Actual transports must enforce closure, not just service-call counters.
- A current-cutoff LIVE_OBSERVED dataset may include retained historical final
  vintages genuinely received before that cutoff. Preserve their actual receipt
  timestamps and identify final-vintage origin. Do not relabel the historical
  reconstructed replay or claim contemporary historical availability.
- Public readiness precedes every private request. No private output persistence.

Reviewed raw authority SHA-256 identities:

| Authority | SHA-256 |
| --- | --- |
| FPL rights | `1691229b120054b8d4c65c7d74e5a0f6d9d11947f1a8f261d26649314268011d` |
| Parent Odds rights | `78fc27ce1ef776b96c77d5c8b7e5a676c7ec12a0e2799c0745d406b593faa1ed` |
| OpenFootball rights | `aa351d0662e8943bcd4caf8ca43bba3a87d2d1603b312fb1760751feaeaf5545` |
| DMFP-05 | `de024be01f8e1fdd1bae259ffe9230508870830644da67dc61639cb70cd943dd` |
| DMFP-20 | `7ed484961cf81af1716db6daa51e6fa05ce2584c33bb04c1d59698e3bf934d72` |
