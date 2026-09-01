# Implementation result

Status: implemented pending final exact-SHA CI and independent review.

The FPL-local contract projection and declared-artifact transformation now recurse through
ordinary dictionaries. Every key must remain a JSON string; nested lists, tuples, datetimes and
Decimals then receive the same existing transformations as direct values. Semantic projection
still normalizes exact Decimal text (`0.0` to `0`, `1.2300` to `1.23`) and never converts to binary
float. Declared artifacts preserve their prior Decimal formatting. Non-finite JSON numbers remain
rejected by the parser.

The repository-wide canonical serializer is untouched. Existing frozen FPL payload and semantic
hashes remain unchanged, while equivalent nested-Decimal textual forms and dictionary orders now
produce the same semantic hash. Odds, authentication, current score priors, one-command
orchestration, models, scoring, optimisation, captaincy, writeback and reporting are untouched.

Real Windows/Python 3.13.9 source-tree and external installed-wheel clients both fetched and
successfully parsed the current public bootstrap. The snapshot advanced to the fixtures response
and then exposed a separate current-input adapter limitation: `_canonical_game_setting()` rejects
the parser's exact Decimal values with `INTERNAL_INVARIANT: FPL game settings are invalid`. This
new issue is reported rather than masked or expanded into 001C. The genuine one-command retry
remains independently blocked at `THE_ODDS_API_KEY is missing.`
