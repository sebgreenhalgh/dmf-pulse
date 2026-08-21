# GW1-INPUT-001 source governance

## Verified source identity

- Owner: `openfootball`
- Repository: `https://github.com/openfootball/england`
- Pinned commit: `10fa650c5d0f137f0d71d6b9fc723076060fe80e`
- Licence file: `LICENSE.md`, headed **CC0 1.0 Universal**.
- Underlying-data statement: the repository README states that the
  football.db schema, data and scripts are dedicated to the public domain and
  may be used without restriction.

The candidate builder verifies a clean local checkout at exactly that Git
commit before it parses any source file. Retrieval is external to the runtime
and CI path; its timestamp is recorded in the candidate artifact.

## Selected source files

| Season | Pinned path | SHA-256 |
| --- | --- | --- |
| 2021/22 | `2021-22/1-premierleague.txt` | `592df232fbc7c2f36ec3e643eef608f77fcbf7d8da0706c94c99248d60b932b3` |
| 2022/23 | `2022-23/1-premierleague.txt` | `c85a2f8ac64975435b8359eb923eaa09e48f33d47672c8b32d2c6e99a8cec5f0` |
| 2023/24 | `2023-24/1-premierleague.txt` | `0bfb4a7fffe0b1bf7318955686eafeb28fc9676346ae433259e7409d69551450` |
| 2024/25 | `2024-25/1-premierleague.txt` | `e39716b01af0c8654a9fae7b5555e6b02f506ea05239e0d0eef41936ba80e1e3` |
| 2025/26 | `2025-26/1-premierleague.txt` | `9bb2f7728e8a371888de2734f59e7400670ed14b2f272c4a47858ac5f257cc38` |

`2025-26/1-premierleague-full.txt` was inspected during source verification.
It produced the same completed score totals, but the standard
`1-premierleague.txt` path is selected for a consistent five-file contract.

## Retention and limitations

CC0 permits retention and reuse according to the source repository's stated
dedication. DMF deliberately commits neither raw match rows nor a vendored
copy of the source: this ticket retains only source hashes, aggregate totals,
derived rates and reproducible parser code.

The source licence and README are source-owner assertions, not an independent
warranty of upstream provenance, completeness or accuracy. Human review must
still decide whether those assertions and the derived-only retention approach
are sufficient for future activation. This candidate has no player event data
and cannot unlock player allocation.
