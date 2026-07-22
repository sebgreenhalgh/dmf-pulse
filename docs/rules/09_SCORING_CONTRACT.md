# Scenario Scoring Contract

## Fixture scenario

The input contains:
- fixture ID, Gameweek ID, final team score and complete synthetic participant universe;
- player ID, team, FPL position and official minutes;
- entry/exit/dismissal facts required for clean-sheet/goals-conceded treatment;
- resolved eligible goals and assists;
- saves, penalties, cards, own goals and defensive actions;
- BPS aggregate event counts, including pass attempts/completions and save categories;
- one explicit match-winning-goal count where applicable.

The scorer validates nonnegative counts, legal percentages, player/team relationships and score/event coherence that can be checked from the supplied aggregate scenario. It does not invent missing events.

## FPL components

Apply configured values per fixture:
- appearance uses highest matching band only;
- goal points use FPL position and exclude own goals;
- assists are per resolved eligible assist;
- clean sheets use position, threshold and goals while eligible/on pitch, including configured dismissal continuation;
- saves use complete groups;
- defensive contribution rewards respect threshold and per-fixture cap;
- GK/DEF goals-conceded deduction uses complete configured goal groups;
- penalty misses, cards and own goals are linear configured deductions;
- bonus is appended only after all players’ BPS are calculated.

Every result exposes all components even when zero, `bps`, `bonus`, `total`, ruleset ID/version/hash and scenario identity.

## BPS

Reference rules are configuration, not literals. Required behaviors:
- appearance bands mutually exclusive;
- direct penalty goal versus position non-penalty goal mutually exclusive;
- pass-completion bands mutually exclusive and require the minimum attempts;
- grouped events use floor division;
- positive and negative categories sum exactly;
- target 2026/27 draft changes are recorded but not used for production scoring while incomplete.

## Bonus-ranking eligibility

For RUL-002 aggregate fixture scenarios, a row with `official minutes = 0` is a Gameweek placeholder, not a fixture participant. It must receive zero BPS and zero bonus and is excluded from bonus rank groups. Every player with positive official minutes enters the joint BPS/bonus universe. This prevents zero-minute placeholders from receiving tie awards.

## Bonus ties

Use competition ranking:
- sort groups by descending distinct BPS;
- the first group has rank 1; the next rank advances by the size of the prior group;
- rank 1 receives 3, rank 2 receives 2, rank 3 receives 1, later ranks receive 0;
- every player in a tied group receives the rank’s award.

This handles ordinary and unusual ties without example-specific branches.

## Gameweek

A Gameweek result sums fixture component totals for the same player and ruleset. It preserves fixture breakdowns. A blank is zero only because no assigned fixture exists. Manager multipliers, autosubs, transfer hits and chips are outside RUL-002.
