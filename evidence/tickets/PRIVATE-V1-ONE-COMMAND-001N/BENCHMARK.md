# PRIVATE-V1-ONE-COMMAND-001N deterministic runtime evidence

The final source state ran the repository-owned, provider-shaped three-Gameweek one-command replay
once on the Windows acceptance host. This is informational wall-clock evidence, not a CI timing
threshold. No network, real credential, private entry identifier, or retained provider body was
used.

| Instrumented stage | Milliseconds |
|---|---:|
| Horizon input construction | 1,305.5666 |
| Stage 7, GW2 | 26,819.6929 |
| Stage 7, GW3 | 27,356.2199 |
| Stage 7, GW4 | 27,360.3555 |
| Stage 8/9, GW2 | 9,994.6637 |
| Stage 8/9, GW3 | 9,253.6977 |
| Stage 8/9, GW4 | 9,267.0648 |
| Joint scenario assembly, GW2 | 523.6651 |
| Joint scenario assembly, GW3 | 523.0742 |
| Joint scenario assembly, GW4 | 522.3527 |
| Action generation | 10.9583 |
| Stage-10 tactical batch | 269.6390 |
| Stage-11 exact policy solve | 11,344.5455 |
| Report and paired comparator | 476.2463 |
| Sum of instrumented stages | 125,027.7422 |
| Pytest case wall clock | 132,100 ms |

Stage 7 accounts for about 81.54 seconds of the measured stage total, Stage 8/9 for about 28.52
seconds, and the exact Stage-11 solve for about 11.34 seconds. The accepted tactical batch remains
shared; the horizon frontier selects from already evaluated complete policies and does not launch a
second Stage-10 evaluation family.
