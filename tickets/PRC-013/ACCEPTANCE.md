# PRC-013 acceptance boundary

The implementation is based directly on immutable Stage-12 merge
`ce7fe8f4354d95a477afcf6eed45f63cf0ab772e`. Engineering completion does not activate the
target-season model and does not constitute human acceptance.

Required proofs:

- immutable UTC price observations retain observed/received/usable times, rights, dataset mode
  and hashes;
- historical features enforce `usable_at <= information_cutoff` and reject future calibration;
- update labels preserve interval censoring, ambiguity and correction lineage;
- counter resets/corrections never become fictitious negative transfer flow;
- P0/P1/P2 probabilities are coherent, deterministic and chronologically fitted;
- threshold diagnostics are always `MODEL_INFERRED`;
- recurrent paths support repeated and opposite-direction changes on integer price units;
- every expected price is derived from its discrete PMF;
- Stage-11's accepted selling-price function and ownership spells are reused unchanged;
- Stage-12 proper probability/distribution scoring and chronological folds are reused;
- ACT/WAIT compares full utility and cannot be inferred from rise probability alone;
- ordinary tests and CLI remain offline and use synthetic/replay or rights-approved inputs;
- production status remains fail-closed until rights, target-season calibration and human gates pass;
- the implementation session created no PR, merge or accepted tag; the independent-review session
  may publish only an unmerged draft PR while human acceptance remains false.
