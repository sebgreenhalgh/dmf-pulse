# MIN-007R4 remediation result

- Ticket: `MIN-007R4`; branch: `stage/A7/MIN-007-basic-minutes-model`.
- Required parent: `1ea36d831e18157a669b257a3761f8a9c9a5cdf7`.
- Added one narrow exact finite-Decimal utility using integer coefficient/exponent alignment. Stored 91-bin PMFs now require an exact sum of one; production correction constructs the residual exactly as `1 - other_sum` while leaving the precision-60 calculation and correction-bin ranking frozen.
- Candidate START+BENCH validation now compares exact integer-scaled values against one, so 1E-300, 1E-1000, and the tiny half-plus-half excess are rejected under ambient precisions 10, 28, 60, and 256. Exact 0.7+0.3 and 1+0 remain accepted; NaN and infinities fail closed.
- The adversarial regression file contains 24 tests, including the required model-copy hidden-excess probe and exact production PMF checks under all four ambient precisions.
- All 15 literal acceptance commands pass. Frozen D and E oracle identities remain unchanged; repository validation reports zero errors and secret scanning reports zero findings.
- Frozen identities: B `1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3`, C `baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96`, D `8e0b41037d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422`, stable E `60afa72dbc0340615e2786783ec56186ce1a2e11a497aa4f872a9b0890bc10ee`, rotation E `24a16e024f3df86872f3bc113a1151fdfc1b87acc8cff97ddc664e25d1301e85`, hard-ineligible E `0215e111fe4eed650d9cd030b41a84ca0b698aac90bc4879e172ae6456310c81`, new-signing E `bafda12ff52ea241bc23fd97c153a0cd4cf21c500df798e17e9b855559177f13`.
- Exactly one bounded completion commit is created after this evidence; no push, merge, rebase, reset, restore, clean, stash, tag, or amend is used.
