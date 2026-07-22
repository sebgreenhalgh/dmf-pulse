# Reference BPS and 2026/27 Delta Contract

## Reference 2025/26 table

Implement from DMFP-02 section 13.2 as REFERENCE_ONLY configuration:

Positive:
- appearance 1–60 minutes: 3; over 60: 6;
- direct penalty goal: 12;
- non-penalty goal GK/DEF 12, MID 18, FWD 24;
- assist 9;
- GK/DEF clean sheet 12;
- penalty save 8;
- save inside box 3; save outside box 2;
- successful open-play cross 1;
- big chance created 3;
- each 2 CBI 1;
- each 3 recoveries 1;
- key pass 1;
- successful tackle 2;
- successful dribble 1;
- match-winning goal 3;
- goal-line clearance 9;
- foul won 1;
- shot on target 2;
- pass completion with >=30 attempts: 70–79% 2, 80–89% 4, >=90% 6.

Negative:
- GK/DEF each goal conceded -4;
- penalty conceded -3;
- penalty miss -6;
- yellow -3; red -9; own goal -6;
- big chance missed -3;
- error leading to goal -3; error leading to attempt -1;
- being tackled -1;
- foul conceded -1; offside -1; shot off target -1.

## Checked 2026/27 deltas

The target draft records, with source `SRC-FPL-2026-BPS-001`:
- remove the being-tackled -1 category;
- CBI grouped reward becomes 1 BPS per 3, not per 2;
- any save gets 2 BPS;
- inside-box save adds 1 BPS;
- big-chance save adds 1 BPS;
- penalty-save category becomes 7 BPS because the big-chance-save metric contributes separately.

Do not infer any unannounced change. Do not score the target draft as ACTIVE until the complete target table and overlap semantics are reviewed and approved.
