# 2026/27 FPL rules verification report

Verification cutoff: 2026-08-14
Ruleset: `fpl-2026-27`
Version inspected: `0.1.0-prelaunch.1`
Schema revision: `1.1`
Outcome: `READY_TO_COMMIT_PLAYER_POINTS`

The official 2026/27 game, Help/Rules surface, launch announcements, and
bootstrap configuration are live. The factual rules below were independently
checked against those current official sources; no 2025/26 value was treated as
evidence of 2026/27 continuity.

RUL-002R1 adds a backward-compatible schema 1.1 representation for the verified
PLAYER_POINTS rules and for future manager-state completion. Sebastian
Greenhalgh approved the bounded bonus-tie interpretation for PLAYER_POINTS at
`2026-08-14T15:08:25Z`. The exact capability is source-backed, has no blockers,
and is production eligible.
The global ruleset remains `CAPTURED_UNVERIFIED` and
`production_eligible: false`; TRANSFER_STATE, CHIP_STATE, and FULL_SEASON remain
blocked. Only the bounded PLAYER_POINTS interpretation approval described below
was performed. No other interpretation, capability, or ruleset approval, and no
activation, was performed.

## Capability result matrix

| Capability | Dependency scope | Result | Blockers |
|---|---|---|---|
| `PLAYER_POINTS` | Positions, participation, scoring, assist eligibility, BPS and bonus | `PRODUCTION_ELIGIBLE`; source-backed; blockers empty | `INT-FPL-2026-BONUS-TIES-001` approved for this capability only |
| `GW1_INITIAL_SQUAD` | PLAYER_POINTS plus initial squad/formation/club quota/budget/purchase-price/GW1 deadline rules | `BLOCKED` | Manager-state authoring data has not yet been promoted from the verified capture |
| `TRANSFER_STATE` | GW1 plus transfer transitions and deterministic selling price | `BLOCKED` | Transfer state is unpromoted; below-purchase-price selling branch lacks official clarification or approval |
| `CHIP_STATE` | Transfer state plus split chip inventories/windows/effects and substitutions | `BLOCKED` | Chip and automatic-substitution state is unpromoted |
| `FULL_SEASON` | Complete rules closure including all deadlines, finality and special events | `BLOCKED` | Transfer, price, chip, finality and special-event families remain blocked |

## Official source matrix

| Source ID | Official source | Published | Accessed | Rule coverage | Verification result |
|---|---|---:|---:|---|---|
| `SRC-FPL-2026-RULES-001` | [Fantasy Premier League Game Rules & Help](https://fantasy.premierleague.com/help/rules) | Living page | 2026-08-14 | Squad, formation, lineup, substitutions, captaincy, transfers, selling price, chips, deadlines, scoring, assists, BPS, ties | `VERIFIED`; controlling current 2026/27 rules surface |
| `SRC-FPL-2026-BOOTSTRAP-001` | [Official FPL bootstrap configuration](https://fantasy.premierleague.com/api/bootstrap-static/) | Living API | 2026-08-14 | 2026/27 static-content namespace, position quotas/bounds, budget, squad/lineup sizes, club limit, scoring values, transfer limits/sell fee, chips, all 38 deadlines, empty Gameweek overrides | `VERIFIED`; authoritative current game configuration |
| `SRC-FPL-2026-BPS-001` | [Changes to Bonus Points System](https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system) | 2026-07-20 | 2026-08-14 | 2026/27 BPS deltas and bonus tie allocation | `VERIFIED` |
| `SRC-FPL-2026-CHIPS-001` | [What’s happening with FPL chips in 2026/27](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627) | 2026-07-20 | 2026-08-14 | Two half-season chip sets, expiry/refresh, one-chip limit, effects, Free Hit restrictions | `VERIFIED` |
| `SRC-FPL-2026-DC-001` | [Defensive contribution points in 2026/27](https://www.premierleague.com/en/news/4361991/whats-happening-with-defensive-contribution-points-in-202627-fantasy) | 2026-07-20 | 2026-08-14 | Defender and midfielder/forward events, thresholds, award and cap | `VERIFIED` |
| `SRC-FPL-2026-PRICE-001` | [2026/27 Price Change Predictor](https://www.premierleague.com/en/news/4680462/whats-new-in-202627-fantasy-price-change-predictor) | 2026-07-21 | 2026-08-14 | Price-lock deadline, daily change time, predictor status | `VERIFIED` |
| `SRC-FPL-2026-CHANGES-001` | [All changes to FPL for 2026/27](https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627) | 2026-07-31 | 2026-08-14 | Launch, BPS/chips/DC continuity, five-transfer bank, Gameweek finality | `VERIFIED`; current page date supersedes stale local metadata |

## Rule verification table

`UNCHANGED—REVERIFIED` means the proposed value equals the local 2025/26
reference but was independently established from a current 2026/27 official
source. `CHANGED` means the official target-season rule differs.
`CAPABILITY-BLOCKED` means schema 1.1 can represent the rule but the applicable
manager-state data has not been promoted to a verified capability.

| Rule | 2025/26 reference | Proposed 2026/27 | Official source | Verification result |
|---|---|---|---|---|
| Positions and quotas | GK 2, DEF 5, MID 5, FWD 3 | GK 2, DEF 5, MID 5, FWD 3 | Rules; bootstrap `element_types` | `UNCHANGED—REVERIFIED` |
| Formation bounds | GK 1–1, DEF 3–5, MID 2–5, FWD 1–3 | GK 1–1, DEF 3–5, MID 2–5, FWD 1–3 | Rules; bootstrap `element_types` | `UNCHANGED—REVERIFIED` |
| Squad | 15; £100.0m; max 3/club | 15; £100.0m (`1000` tenths); max 3/club | Rules; bootstrap `game_config.rules` | `UNCHANGED—REVERIFIED` |
| Starting lineup / bench | 11 / 4 | 11 / 4 | Rules; bootstrap | `UNCHANGED—REVERIFIED` |
| Captain / vice | ×2; vice fallback | ×2; vice replaces captain only when captain plays no minutes; neither playing means no doubling | Rules | `UNCHANGED—REVERIFIED`; manager-state data `CAPABILITY-BLOCKED` |
| Automatic substitutions | Priority/formation behavior not encoded in reference | GK-for-GK; outfield bench priority subject to legal formation; a card counts as playing | Rules | `VERIFIED`; schema 1.1 representable; `CAPABILITY-BLOCKED` |
| Appearance points | 1 point for 1–59; 2 for ≥60; stoppage excluded | Same | Rules scoring table | `UNCHANGED—REVERIFIED` |
| Goal points | GK 10, DEF 6, MID 5, FWD 4 | Same | Rules scoring table; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Assist points | 3 | 3 | Rules scoring table; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Clean sheets | GK/DEF 4, MID 1, FWD 0; ≥60; retain after normal substitution | Same; no goal conceded while on pitch; stoppage excluded | Rules | `UNCHANGED—REVERIFIED` |
| Goalkeeper saves | Every 3 saves = 1; uncapped | Same | Rules scoring table; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Penalty saves / misses | +5 / −2; shootouts excluded | +5 / −2; shootouts excluded | Rules scoring table; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Defensive contributions—DEF | 2 for ≥10 CBIT; cap 2 | Same | Rules; DC announcement | `UNCHANGED—REVERIFIED` |
| Defensive contributions—MID/FWD | 2 for ≥12 CBIRT; cap 2 | Same | Rules; DC announcement | `UNCHANGED—REVERIFIED` |
| Goals conceded | GK/DEF −1 per 2; continues after dismissal | Same | Rules scoring/red-card text; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Cards | Yellow −1; red −3 including yellow deductions | Same | Rules; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Own goals | −2 | −2 | Rules; bootstrap scoring | `UNCHANGED—REVERIFIED` |
| Bonus award | Competition ranks 1/2/3 receive 3/2/1 | Same | Rules; BPS announcement | `UNCHANGED—REVERIFIED` |
| Bonus ties | 1st tie: 3,3,1; 2nd tie: 3,2,2; 3rd tie: 3,2,1,1 | The same three published examples plus approved `GENERAL_COMPETITION_RANKING` generalisation | Rules; BPS announcement; `INT-FPL-2026-BONUS-TIES-001` | Published examples `UNCHANGED—REVERIFIED`; complete official algorithm remains unresolved, but the bounded PLAYER_POINTS ambiguity is satisfied by the explicit human-approved interpretation |
| Assist eligibility policy | 2025/26 reference policy | Current rules explicitly cover passes, ≤1 defensive touch, inside/outside-box intent, inadvertent touches, rebounds, own goals, penalties/free-kicks, handballs, exclusions and FPL/Opta finality | Rules | `UNCHANGED—REVERIFIED`; encoded in schema 1.1 PLAYER_POINTS data |
| Free transfers | Cap 5; hit −4 | 1 per GW after first deadline; bank to 5; −4 for each extra; maximum 20 transfers/GW except Wildcard/Free Hit | Rules; bootstrap; changes announcement | `UNCHANGED—REVERIFIED` for cap/hit; schema 1.1 representable; `CAPABILITY-BLOCKED` |
| Pre-season transfers | Not encoded | Unlimited and free until first deadline | Rules | `VERIFIED`; schema 1.1 representable; `CAPABILITY-BLOCKED` |
| Free-transfer/chip interaction | Not encoded | Saved free transfers retained after Wildcard or Free Hit | Rules | `VERIFIED`; schema 1.1 representable; `CAPABILITY-BLOCKED` |
| Price unit | £0.1m | £0.1m (`ui_currency_multiplier: 10`) | Bootstrap | `UNCHANGED—REVERIFIED` |
| Price-change mechanism | Threshold algorithm undisclosed | Popularity-driven; daily at 00:00 UK time after GW1; official predictor is guidance, not guarantee; exact threshold remains undisclosed | Rules; price announcement | `UNCHANGED—REVERIFIED` for undisclosed algorithm; timing is `CHANGED/ADDED` |
| Selling price | Not encoded | If current > purchase, retain half the rise rounded down to £0.1m (`transfers_sell_on_fee: 0.5`); the target-season controlling sources checked here do not explicitly state the loss branch | Rules; bootstrap | Rise branch `VERIFIED`; loss branch genuinely unresolved; `CAPABILITY-BLOCKED` |
| Chip inventory | Two each across season | Two each: Wildcard, Free Hit, Triple Captain, Bench Boost; first set expires at GW19 deadline and cannot carry; second set refreshes afterward | Rules; chips/changes announcements; bootstrap | `UNCHANGED—REVERIFIED`; schema 1.1 representable; `CAPABILITY-BLOCKED` |
| Chip concurrency | One/GW | One/GW | Rules; chips announcement | `UNCHANGED—REVERIFIED` |
| Triple Captain | Captain ×3 | Captain ×3 instead of ×2; cancellable before deadline | Rules; chips announcement | `UNCHANGED—REVERIFIED`; schema 1.1 effect representable; `CAPABILITY-BLOCKED` |
| Bench Boost | Bench scores included | Bench scores included; cancellable before deadline | Rules; chips announcement | `UNCHANGED—REVERIFIED`; schema 1.1 effect representable; `CAPABILITY-BLOCKED` |
| Wildcard | Unlimited permanent free transfers | First available GW2–19; second GW20–38; permanent; includes earlier GW transfers; cannot be cancelled once played | Rules; bootstrap chips | `UNCHANGED—REVERIFIED`; schema 1.1 windows/effect representable; `CAPABILITY-BLOCKED` |
| Free Hit | Unlimited free transfers for one GW | First GW2–19; second GW20–38; prior squad restored next deadline; cannot cancel; not GW1 or consecutive (GW19 use blocks GW20) | Rules; chips announcement; bootstrap chips | `UNCHANGED—REVERIFIED`; schema 1.1 restrictions/effect representable; `CAPABILITY-BLOCKED` |
| Deadline policy | One synthetic reference deadline | 90 minutes before first match; no change within 24 hours; current official GW1–38 values in appendix | Rules; bootstrap | `CHANGED` from synthetic reference |
| Gameweek finality | Not encoded | 09:00 UK time on day after final match | Changes announcement | `CHANGED/ADDED`; schema 1.1 representable; `CAPABILITY-BLOCKED` |
| Special events | `[]` | No current scheduled rule overrides; bootstrap exposes empty `overrides.rules/scoring/element_types` and null multiplier for GW1–38 | Bootstrap | `UNCHANGED—REVERIFIED`; refresh on official config change |
| Source manifest | One internal reference source | Seven current official 2026/27 sources above | Source URLs above | `CHANGED`; leaf-level source locators compiled in schema 1.1 |

## Complete 2026/27 BPS matrix

| BPS event | 2025/26 reference | Official 2026/27 | Source | Verification result / interpretation |
|---|---:|---:|---|---|
| Appearance 1–60 minutes | 3 | 3 | Rules | `UNCHANGED—REVERIFIED` |
| Appearance >60 minutes | 6 | 6 | Rules | `UNCHANGED—REVERIFIED` |
| Non-penalty goal GK/DEF/MID/FWD | 12/12/18/24 | 12/12/18/24 | Rules | `UNCHANGED—REVERIFIED` |
| Penalty scored | 12 | 12 | Rules | `UNCHANGED—REVERIFIED`; exclusive of position-goal BPS |
| Assist | 9 | 9 | Rules | `UNCHANGED—REVERIFIED` |
| Clean sheet GK/DEF, ≥60 | 12 | 12 | Rules | `UNCHANGED—REVERIFIED` |
| Any save | Inside 3; outside 2 | 2 | Rules; BPS announcement | `CHANGED` event basis |
| Save from inside box | Included in inside 3 | +1 | Rules; BPS announcement | `CHANGED`; stacks with any-save BPS |
| Big-chance save | Not present | +1 | Rules; BPS announcement | `ADDED`; distinct additive event in schema 1.1 |
| Penalty save | 8 | 7 | Rules; BPS announcement | `CHANGED`; penalty is a big chance, so base 7 plus applicable save BPS preserves additive accounting |
| Successful open-play cross | 1 | 1 | Rules | `UNCHANGED—REVERIFIED` |
| Big chance created | 3 | 3 | Rules | `UNCHANGED—REVERIFIED` |
| CBI group | 1 per 2 | 1 per 3 | Rules; BPS announcement | `CHANGED` |
| Recovery group | 1 per 3 | 1 per 3 | Rules | `UNCHANGED—REVERIFIED` |
| Key pass / successful tackle / successful dribble | 1 / 2 / 1 | 1 / 2 / 1 | Rules | `UNCHANGED—REVERIFIED` |
| Match-winning goal / goal-line clearance | 3 / 9 | 3 / 9 | Rules | `UNCHANGED—REVERIFIED` |
| Foul won / shot on target | 1 / 2 | 1 / 2 | Rules | `UNCHANGED—REVERIFIED` |
| Pass completion, ≥30 attempts | 70–<80: 2; 80–<90: 4; 90–100: 6 | Same | Rules | `UNCHANGED—REVERIFIED`; highest matching band only |
| Goal conceded GK/DEF | −4 each | −4 each | Rules | `UNCHANGED—REVERIFIED` |
| Penalty conceded / missed | −3 / −6 | −3 / −6 | Rules | `UNCHANGED—REVERIFIED` |
| Yellow / red / own goal | −3 / −9 / −6 | −3 / −9 / −6 | Rules | `UNCHANGED—REVERIFIED` |
| Big chance missed | −3 | −3 | Rules | `UNCHANGED—REVERIFIED` |
| Error leading goal / attempt | −3 / −1 | −3 / −1 | Rules | `UNCHANGED—REVERIFIED` |
| Being tackled | −1 | Removed | Rules; BPS announcement | `CHANGED/REMOVED`; encoded explicitly as `REMOVED`, not as zero |
| Foul conceded / offside / shot off target | −1 / −1 / −1 | −1 / −1 / −1 | Rules | `UNCHANGED—REVERIFIED` |

## Current official deadlines

These are the official bootstrap values accessed on 2026-08-14. The controlling
rules say deadlines are subject to change but will not change within 24 hours of
the scheduled time; any official change requires a new captured ruleset version.

| GW | Deadline UTC | GW | Deadline UTC |
|---:|---|---:|---|
| 1 | 2026-08-21T17:30:00Z | 20 | 2027-01-06T18:30:00Z |
| 2 | 2026-08-28T17:30:00Z | 21 | 2027-01-16T13:30:00Z |
| 3 | 2026-09-04T17:30:00Z | 22 | 2027-01-23T13:30:00Z |
| 4 | 2026-09-12T12:30:00Z | 23 | 2027-01-30T13:30:00Z |
| 5 | 2026-09-18T17:30:00Z | 24 | 2027-02-06T13:30:00Z |
| 6 | 2026-10-10T12:30:00Z | 25 | 2027-02-10T18:30:00Z |
| 7 | 2026-10-17T12:30:00Z | 26 | 2027-02-20T13:30:00Z |
| 8 | 2026-10-24T12:30:00Z | 27 | 2027-02-27T13:30:00Z |
| 9 | 2026-10-31T13:30:00Z | 28 | 2027-03-03T18:30:00Z |
| 10 | 2026-11-07T13:30:00Z | 29 | 2027-03-13T13:30:00Z |
| 11 | 2026-11-21T13:30:00Z | 30 | 2027-03-20T13:30:00Z |
| 12 | 2026-11-28T13:30:00Z | 31 | 2027-04-10T12:30:00Z |
| 13 | 2026-12-02T18:30:00Z | 32 | 2027-04-17T12:30:00Z |
| 14 | 2026-12-05T13:30:00Z | 33 | 2027-04-24T12:30:00Z |
| 15 | 2026-12-12T13:30:00Z | 34 | 2027-05-01T12:30:00Z |
| 16 | 2026-12-19T13:30:00Z | 35 | 2027-05-08T12:30:00Z |
| 17 | 2026-12-26T13:30:00Z | 36 | 2027-05-15T12:30:00Z |
| 18 | 2026-12-30T18:30:00Z | 37 | 2027-05-23T12:30:00Z |
| 19 | 2027-01-02T13:30:00Z | 38 | 2027-05-30T13:30:00Z |

## Schema 1.1 implementation result

Schema 1.1 resolves the representational gaps without changing v1.0 canonical
semantics:

1. BPS now has separate `save_any`, `save_inside_box_additional`, and
   `save_big_chance_additional` values; player events carry big-chance saves as
   a distinct subset, and `being_tackled: REMOVED` is explicit.
2. Assist eligibility is versioned data covering the current defensive-touch,
   intent, rebound, own-goal, set-piece, handball-adjacent, possession and
   official-finality rules while exact scoring still consumes resolved counts.
3. Participation data fixes fixture scope, official-minute basis, position
   basis, appearance/bonus eligibility, and unmapped-position rejection.
4. Rule verification records bind every PLAYER_POINTS leaf to exact official
   source IDs and per-rule locators.
5. Capability dependencies are governed and transitive. PLAYER_POINTS cannot
   silently omit scoring, assists or BPS, and it does not inherit transfer or
   chip machinery.
6. Automatic substitutions, transfer transitions, deterministic selling-price
   branches, split chip inventory/windows/effects, and Gameweek finality have
   strict schema shapes for later manager-state promotion.
7. Interpretation decisions are immutable, content-hashed, source-referenced,
   review-triggered and auditable. An unapproved interpretation never satisfies
   production eligibility.

The manager-state families remain typed unknowns in this ruleset. This is a
data-promotion blocker, not a PLAYER_POINTS schema blocker.

## Genuinely unresolved official-source items

1. The current target-season Help/Rules text and bootstrap configuration verify
   the 50% sell-on fee and floor-rounded profit branch. They do not explicitly
   state the selling-price result when current price is below purchase price.
   A prior-season explainer does, but it is not admissible as 2026/27 authority.

An explicit official clarification/configuration or a separately approved
TRANSFER_STATE interpretation is required before that capability can become
production eligible.

## PLAYER_POINTS interpretation approval

- Decision: `INT-FPL-2026-BONUS-TIES-001`
- Scope: `PLAYER_POINTS` only, season `2026/2027`
- Approved by: Sebastian Greenhalgh
- Approved at: `2026-08-14T15:08:25Z`
- Interpretation: `GENERAL_COMPETITION_RANKING`
- Pre-approval decision hash:
  `f954cdbdcc3fe84930271c618500c4a6cf76a705788ad84a399f25687f6672fa`
- Approved decision hash:
  `dfe10d4dabf8183c10f4a61d3bd2361bd54ee78d24c96ee9d38da42becfbaa49`
- Pre-approval capability hash, now superseded:
  `028818acec741e82d2ad10c4789171731d00cb5e4dd1d6efeda5bc6c2f26fe52`
- Approved capability hash:
  `2f0fcaee9e5670dcc83d7704de0d220eacbc7f532d862504f530fe57795267b4`

The record explicitly says this is a human interpretation rather than an
official-source claim. FULL_SEASON receives an `out_of_scope` blocker for this
decision and cannot inherit the bounded approval.

## Verification command results

- `dmf rules validate`: exit 0; schema 1.1 valid; global status remains
  `CAPTURED_UNVERIFIED`; global `production_eligible: false`.
- `dmf rules compile`: exit 0; tracked schema 1.1 artifact written. Recompiling
  twice to the same path reproduced ruleset hash
  `afa1364d7d7adfc632d73782f46707bb4f92d3961ca1946d4c8cab0496c2f8ff`.
- `dmf rules compile-capability ... PLAYER_POINTS`: exit 0; two compilations
  reproduced capability hash
  `2f0fcaee9e5670dcc83d7704de0d220eacbc7f532d862504f530fe57795267b4`.
- `dmf rules hash`, `show`, and reference `diff`: exit 0. The reference diff
  contains 56 changes: 31 added, 7 changed and 18 removed paths. The scoring
  changes are the assist policy, participation policy, additive save events,
  CBI group size, penalty-save BPS, explicit being-tackled removal and tie
  policy; manager-family removals reflect retained typed unknowns.
- Schema 1.1 compatibility locks reproduce the original v1.0 hashes:
  reference `12271ab0...e0c1139`; synthetic `98e8614d...b0aab8`.
- Focused rules unit/property/contract/golden/CLI tests, explicit 2026/27
  regressions, and unit assurance: `481 passed`.
- `ruff format --check .`: 301 files formatted; `ruff check .`: pass;
  `mypy src/dmf_pulse`: pass for 111 source files.
- First-party secret scan: pass with zero findings.
- Repository validator remains expectedly red because
  `evidence/tickets/RUL-002/current_manifest.json` is commit-bound to the prior
  accepted tree and therefore reports the intentional working-tree changes.
  No false COMPLETE evidence or commit identity was generated.
- One complete repository collection was run: 1,434 tests were collected.
  The initial command passed 1,226 tests; 205 PostgreSQL tests could not start
  until the repository-prescribed disposable database environment was supplied;
  the installed-wheel test had the same missing database prerequisite; one
  database-boundary test skipped; and the commit-bound current-manifest test
  failed as expected on the uncommitted tree. Follow-up execution using the
  canonical PostgreSQL 18.4 container, migrations, `PGPASSWORD=changeme`, and
  the credential-free test URL passed all 205 PostgreSQL tests, the wheel test,
  and the boundary test. Thus all 1,433 product tests are accounted for as
  passing; only the intentionally stale commit-bound manifest test remains.

The exact changed-file list is taken from the final `git status` and is reported
in the handoff alongside this report.

## Compiled artifact and approval gate

The tracked ruleset artifact remains fail-closed globally. The separately
approved PLAYER_POINTS artifact is production eligible but is not a global
approval or active ruleset.

- Ruleset artifact: `artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.schema-v1.1.json`
- Ruleset artifact SHA-256: `57f333fa499d3b619c92d9b36d7b93ed9c22af2c173b7aef00e36f421c653706`
- Ruleset hash: `afa1364d7d7adfc632d73782f46707bb4f92d3961ca1946d4c8cab0496c2f8ff`
- PLAYER_POINTS artifact: `artifacts/rules/fpl-2026-27-0.1.0-prelaunch.1.player-points.json`
- PLAYER_POINTS artifact SHA-256: `6e0e295c5d21936ab3d6101b8e8ece9d6835d45c2580bd22e68c3562518afa8b`
- PLAYER_POINTS capability hash: `2f0fcaee9e5670dcc83d7704de0d220eacbc7f532d862504f530fe57795267b4`
- Status: `CAPTURED_UNVERIFIED`
- Global production eligible: `false`
- PLAYER_POINTS production eligible: `true`
- PLAYER_POINTS blockers: `[]`
- Interpretation approval performed: yes, PLAYER_POINTS only
- Activation performed: no

No global `approved: true` approval record is proposed. The only safe global
record remains the following non-approval record; it was not written and must
not be passed to the activation command.

```json
{
  "ruleset_id": "fpl-2026-27",
  "ruleset_version": "0.1.0-prelaunch.1",
  "approved": false,
  "approved_at": null,
  "approved_by": null,
  "ruleset_hash": "afa1364d7d7adfc632d73782f46707bb4f92d3961ca1946d4c8cab0496c2f8ff"
}
```
