Wave005 account qualification requires preserving unknown quota fields instead
of inventing response headers. `QualifiedOperatorQuota` is a separate input
contract. The original five-field provider-response QuotaState is unchanged.

Only these exact reviewed input-annotation additions are allowed by the retained
historical provider freezes:

- client.py SHA256
  `996f134785a8f70a369688aa977cae764cadc632131f1750a4b222130efca803`:
  import QualifiedOperatorQuota and add it to three input parameter unions.
- transient.py SHA256
  `e73d0b95d9f11ec47ec81e2ee05448002db2c2a276a21b1a7a2e369a04347086`:
  import QualifiedOperatorQuota and add it to the constructor input union.

No request/response, retry, quota arithmetic, rights ordering, parser, market
normalisation, model or solver algorithm changes in either file. Historical
hash maps remain intact and only the exact new hashes are additional matches.

Two native FPL permission additions are separately removed by an exact-fragment
test normalizer before the old source equality assertions. One checks supplier
authority before legacy native credential preload; the other forwards the native
permission marker through the existing one-shot wrapper. Every other historical
source byte must still compare equal. Altered reviewed fragments are rejected;
unrelated appended code remains visible to the equality assertion.
