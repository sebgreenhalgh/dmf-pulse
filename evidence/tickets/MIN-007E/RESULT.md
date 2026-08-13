# MIN-007E result

- Ticket: `MIN-007E`; branch: `stage/A7/MIN-007-basic-minutes-model`.
- Accepted parent: `60c583aa5dafff90aeaf2647d2b6cf9eeef950e9`.
- Required commit message: `MIN-007E add coherent lineup sampler`.
- Acceptance ledger: all 15 literal commands passed with zero skipped tests.

## Frozen sampler outputs

- `stable_xi`: scenario set `60afa72dbc0340615e2786783ec56186ce1a2e11a497aa4f872a9b0890bc10ee`; semantic `01ceb8d95b4a5f27bc302c8fc3d379db8316dec2185ee7e4a136577c528826f6`.
- `high_rotation`: scenario set `24a16e024f3df86872f3bc113a1151fdfc1b87acc8cff97ddc664e25d1301e85`; semantic `4531ec313efb934650a3f0f2795636f705fdf3b62a4f9f3a5922105ffeb3c7dd`.
- `hard_ineligible`: scenario set `0215e111fe4eed650d9cd030b41a84ca0b698aac90bc4879e172ae6456310c81`; semantic `823fc9515300bec30819ccd28cf3e020f8c27e7f5c3c7ecff19fe9ce00399f39`.
- `new_signing`: scenario set `bafda12ff52ea241bc23fd97c153a0cd4cf21c500df798e17e9b855559177f13`; semantic `e90758b043d1b9eecbf8e4c5b7e55b1b9a1e85209d0d68230486ca79152f41b9`.
- `insufficient_eligible_squad`: `BLOCKED / INSUFFICIENT_ELIGIBLE_SQUAD`; semantic `8e265c522122b8d9d53133132adec910865ca84c3d5a207caea08553a20622cd`.
- `stable_xi_alt_seed`: scenario set `d48aff9eac014cddde02efdcde7fc7130a8fb10dfa43d457543e05d7817cc20f`; semantic `0267e0b599f441c2ce8871b79d3d536256bdde0dfa671d1bfbaa7a73bd752b12`.
- `zero_weight_bench_gk_block`: `BLOCKED / INSUFFICIENT_ELIGIBLE_SQUAD`; semantic `52e65817a9c5c8bb69fbfcbc4922c1c6427409eb0026609fd99215b7c71b63d9`.

## Regression and security

- MIN-007B dataset SHA unchanged: `1466a5dcc9104a2d26f9c6b286d2717b6460423503026f05a58d3a26de040be3`.
- MIN-007C role artifact SHA unchanged: `baf70ee76b8a51f4cf3bfda1a1cc33d6ba3f6c304617c8bc42aefdee2b2a1c96`.
- MIN-007D minute artifact SHA unchanged: `8e0b410e37d33127dc26937f9fe7c6ff60867b4f60f0f7a87679f951c5f7e422`.
- The sampler uses exact SHA-256 race bytes, Decimal precision 60, four frozen phases, 256 scenarios, coherent role marginals, and no RNG, float log, filesystem, network, database, subprocess, clock, or credential access.
- Repository validation passed with `error_count=0`; secret scan found zero findings; market regression passed with 75 tests.
