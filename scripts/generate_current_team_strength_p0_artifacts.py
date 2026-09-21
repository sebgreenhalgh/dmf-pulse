"""Generate the reviewed CURRENT-TEAM-STRENGTH-001A-P0 governance artifacts."""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "40b3e1b7391932d133287115106304444bf297e1"
DECIDED_AT = "2026-09-21T17:14:39.069428Z"
MAPPING_DECISION_ID = "CURRENT-TEAM-STRENGTH-001A-P0#historical-club-identity-v1"
MAPPING_AUTHORITY = "Sebastian Greenhalgh"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _pretty(value: object) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _reviewed(value: dict[str, Any], hash_field: str = "semantic_sha256") -> dict[str, Any]:
    result = dict(value)
    result[hash_field] = _sha256(value)
    return result


def _season(value: str) -> str:
    return value.replace("-", "/")


SOURCE_HASHES = {
    "2010-11": "a94631cc82fd4034d4da5f5594d32cb191942f0b594e3a9cd9dcf29fe7dfa707",
    "2011-12": "94e29260ec3500ba69e1ffe829576b0c6297cb570ecc223ab13a2fdcae81fb98",
    "2012-13": "d41f9131f9dda654bff9067ffd370468b895b5ed4e9691a4b5cad2b2550fbc8b",
    "2013-14": "821ea8a8a078753993ed1cc9f86fb739ec18824ef07aee1df4e83f6915e29782",
    "2014-15": "2f24151bffd3d377810f3d2e85ead0f1b3dfef00153c6ea31f5e9ced63281a4d",
    "2015-16": "4d8ab70f5d2c29231320be7404310bc1b0fbc6e6be0284e5ee667f581406fead",
    "2016-17": "9c8cdb27355678ab81aacbbabc34a08d00b399aacc28ef4b733da4954a344f17",
    "2017-18": "b635f2442a94aa91d85f282fc5e8f7f5dc4f0d04e3e30c4472102f5708d7548c",
    "2018-19": "e2224d86f0605a5a1b5b019c845cdecb13aca1d88035686d4159b875250d4730",
    "2019-20": "9e1695f85ce5553f762e809dea357ec0a95838939be89569060a83c4e98a302d",
    "2020-21": "21ddf26b48469da530c51ccc4857bf1a534bda3aed08766b55185efb142e9a20",
    "2021-22": "fbdfd426fa18fa2f8630b77de87c082734da495ac4668d6d72f29f76b73b9564",
    "2022-23": "8d09f0f9846981626cdfec48903e1f21e7c79aabe6f92535c9e092e8e79b808b",
    "2023-24": "03e13eafbf78dfe00d7e89dd3bf6643986eb6e8fd86c7664aeb8c5bc0bed88d0",
    "2024-25": "c3d18f552d83382cd4b6b21127adbbfe38e7f8618ddc979fb5404f2df07d0a75",
    "2025-26": "d6070bdf731546ccf97767f062e8af4bd26dd309dee69f6092025bf9c78f43c1",
    "2026-27": "ce34ad5440bca6b19679aa23b4feeb6c8150db1eb0774a4dc0e22624cd85cbc6",
}


CLUB_IDS = {
    "AFC Bournemouth": "01a0c4f8-e0bc-7f69-b0dc-770ddc83e3a8",
    "Arsenal FC": "01a0c4f8-e0bc-7d1a-be3c-a724e6040810",
    "Aston Villa FC": "01a0c4f8-e0bc-7e36-9574-e16ffc1da3bf",
    "Birmingham City": "01a0c4f8-e0bc-7870-bd5d-d9d356f8dd94",
    "Blackburn Rovers": "01a0c4f8-e0bc-7c97-8ad5-45cd67b649dc",
    "Blackpool FC": "01a0c4f8-e0bc-7e4c-a106-c0b3512e7b75",
    "Bolton Wanderers": "01a0c4f8-e0bc-7925-b4f9-7aece951102b",
    "Brentford FC": "01a0c4f8-e0bc-7dbf-ab3d-6a8d8dd29d79",
    "Brighton & Hove Albion FC": "01a0c4f8-e0bc-7128-a139-726538c55c11",
    "Burnley FC": "01a0c4f8-e0bc-7d5b-9084-5a7af83c3b05",
    "Cardiff City": "01a0c4f8-e0bc-7913-a465-a7a3559052cf",
    "Chelsea FC": "01a0c4f8-e0bc-71ce-a570-290a916e6f65",
    "Coventry City FC": "01a0c4f8-e0bc-7fdb-b5f7-b5152bfdfa13",
    "Crystal Palace FC": "01a0c4f8-e0bc-79a1-8f3a-90a98b5f44c5",
    "Everton FC": "01a0c4f8-e0bc-7839-b1ba-7791c432434c",
    "Fulham FC": "01a0c4f8-e0bc-7904-8867-2f27a3c31340",
    "Huddersfield Town": "01a0c4f8-e0bc-7eae-99ed-6d514d63202c",
    "Hull City AFC": "01a0c4f8-e0bc-7714-8ce8-d9ee1469e43d",
    "Ipswich Town FC": "01a0c4f8-e0bc-7461-8e09-b55eb1026ad7",
    "Leeds United FC": "01a0c4f8-e0bc-7253-ae6d-cef2d502db48",
    "Leicester City FC": "01a0c4f8-e0bc-78d4-a520-27e556dfe45c",
    "Liverpool FC": "01a0c4f8-e0bc-7e0d-97dd-5347da800b7d",
    "Luton Town FC": "01a0c4f8-e0bc-7864-a0fb-367cdfe15ade",
    "Manchester City FC": "01a0c4f8-e0bc-7bcd-9ab2-1c9c2d59e64a",
    "Manchester United FC": "01a0c4f8-e0bc-7515-8253-456ec6337a5a",
    "Middlesbrough FC": "01a0c4f8-e0bc-7800-bba1-e528a0d13d05",
    "Newcastle United FC": "01a0c4f8-e0bc-77bc-aa95-9e3213ac3de8",
    "Norwich City FC": "01a0c4f8-e0bc-7edf-bb04-f8f37dc9dd5f",
    "Nottingham Forest FC": "01a0c4f8-e0bc-77e7-b285-5486e1d82bb2",
    "Queens Park Rangers": "01a0c4f8-e0bc-7220-9ae3-fb11c1e90f34",
    "Reading FC": "01a0c4f8-e0bc-7106-bcf0-dec0ae50d825",
    "Sheffield United FC": "01a0c4f8-e0bc-7f8a-8849-0d6aa5a0433e",
    "Southampton FC": "01a0c4f8-e0bc-7e58-9fc8-43adef9017ca",
    "Stoke City": "01a0c4f8-e0bc-7ecf-a6e5-e1de844c0601",
    "Sunderland AFC": "01a0c4f8-e0bc-7d0d-bafd-cfd8f4b6afcd",
    "Swansea City": "01a0c4f8-e0bc-7434-9ab3-19511ca010b6",
    "Tottenham Hotspur FC": "01a0c4f8-e0bc-7e48-b3c5-5248392e35d3",
    "Watford FC": "01a0c4f8-e0bc-7c9f-bb35-f9ef1f885a3d",
    "West Bromwich Albion FC": "01a0c4f8-e0bc-75b0-afa5-5a488cb7b216",
    "West Ham United FC": "01a0c4f8-e0bc-72ee-9a5a-1068df8399c2",
    "Wigan Athletic": "01a0c4f8-e0bc-78fb-8591-7c42f207a1c9",
    "Wolverhampton Wanderers FC": "01a0c4f8-e0bc-7fa3-8655-9ab3e800c17b",
}


ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "AFC Bournemouth": {
        "AFC Bournemouth": (
            "2015-16",
            "2016-17",
            "2017-18",
            "2018-19",
            "2019-20",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        )
    },
    "Arsenal FC": {"Arsenal FC": tuple(SOURCE_HASHES)},
    "Aston Villa FC": {
        "Aston Villa": (
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2019-20",
        ),
        "Aston Villa FC": (
            "2020-21",
            "2021-22",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        ),
    },
    "Birmingham City": {"Birmingham City": ("2010-11",)},
    "Blackburn Rovers": {"Blackburn Rovers": ("2010-11", "2011-12")},
    "Blackpool FC": {"Blackpool FC": ("2010-11",)},
    "Bolton Wanderers": {"Bolton Wanderers": ("2010-11", "2011-12")},
    "Brentford FC": {
        "Brentford FC": ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26", "2026-27")
    },
    "Brighton & Hove Albion FC": {
        "Brighton & Hove Albion": ("2017-18", "2018-19", "2019-20"),
        "Brighton & Hove Albion FC": (
            "2020-21",
            "2021-22",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        ),
    },
    "Burnley FC": {
        "Burnley FC": (
            "2014-15",
            "2016-17",
            "2017-18",
            "2018-19",
            "2019-20",
            "2020-21",
            "2021-22",
            "2023-24",
            "2025-26",
        )
    },
    "Cardiff City": {"Cardiff City": ("2013-14", "2018-19")},
    "Chelsea FC": {"Chelsea FC": tuple(SOURCE_HASHES)},
    "Coventry City FC": {"Coventry City FC": ("2026-27",)},
    "Crystal Palace FC": {
        "Crystal Palace": (
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2017-18",
            "2018-19",
            "2019-20",
        ),
        "Crystal Palace FC": (
            "2020-21",
            "2021-22",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        ),
    },
    "Everton FC": {"Everton FC": tuple(SOURCE_HASHES)},
    "Fulham FC": {
        "Fulham FC": (
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2018-19",
            "2020-21",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        )
    },
    "Huddersfield Town": {"Huddersfield Town": ("2017-18", "2018-19")},
    "Hull City AFC": {
        "Hull City": ("2013-14", "2014-15", "2016-17"),
        "Hull City AFC": ("2026-27",),
    },
    "Ipswich Town FC": {"Ipswich Town FC": ("2024-25", "2026-27")},
    "Leeds United FC": {"Leeds United FC": ("2020-21", "2021-22", "2022-23", "2025-26", "2026-27")},
    "Leicester City FC": {
        "Leicester City": ("2014-15", "2015-16", "2016-17", "2017-18", "2018-19", "2019-20"),
        "Leicester City FC": ("2020-21", "2021-22", "2022-23", "2024-25"),
    },
    "Liverpool FC": {"Liverpool FC": tuple(SOURCE_HASHES)},
    "Luton Town FC": {"Luton Town FC": ("2023-24",)},
    "Manchester City FC": {
        "Manchester City": tuple(list(SOURCE_HASHES)[:10]),
        "Manchester City FC": tuple(list(SOURCE_HASHES)[10:]),
    },
    "Manchester United FC": {
        "Manchester United": tuple(list(SOURCE_HASHES)[:10]),
        "Manchester United FC": tuple(list(SOURCE_HASHES)[10:]),
    },
    "Middlesbrough FC": {"Middlesbrough FC": ("2016-17",)},
    "Newcastle United FC": {
        "Newcastle United": (
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2017-18",
            "2018-19",
            "2019-20",
        ),
        "Newcastle United FC": (
            "2020-21",
            "2021-22",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
            "2026-27",
        ),
    },
    "Norwich City FC": {
        "Norwich City": ("2011-12", "2012-13", "2013-14", "2015-16", "2019-20"),
        "Norwich City FC": ("2021-22",),
    },
    "Nottingham Forest FC": {
        "Nottingham Forest FC": ("2022-23", "2023-24", "2024-25", "2025-26", "2026-27")
    },
    "Queens Park Rangers": {"Queens Park Rangers": ("2011-12", "2012-13", "2014-15")},
    "Reading FC": {"Reading FC": ("2012-13",)},
    "Sheffield United FC": {
        "Sheffield United": ("2019-20",),
        "Sheffield United FC": ("2020-21", "2023-24"),
    },
    "Southampton FC": {
        "Southampton FC": (
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2017-18",
            "2018-19",
            "2019-20",
            "2020-21",
            "2021-22",
            "2022-23",
            "2024-25",
        )
    },
    "Stoke City": {
        "Stoke City": (
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2017-18",
        )
    },
    "Sunderland AFC": {
        "Sunderland AFC": (
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2025-26",
            "2026-27",
        )
    },
    "Swansea City": {
        "Swansea City": (
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2017-18",
        )
    },
    "Tottenham Hotspur FC": {
        "Tottenham Hotspur": tuple(list(SOURCE_HASHES)[:10]),
        "Tottenham Hotspur FC": tuple(list(SOURCE_HASHES)[10:]),
    },
    "Watford FC": {
        "Watford FC": ("2015-16", "2016-17", "2017-18", "2018-19", "2019-20", "2021-22")
    },
    "West Bromwich Albion FC": {
        "West Bromwich Albion": (
            "2010-11",
            "2011-12",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2017-18",
        ),
        "West Bromwich Albion FC": ("2020-21",),
    },
    "West Ham United FC": {
        "West Ham United": (
            "2010-11",
            "2012-13",
            "2013-14",
            "2014-15",
            "2015-16",
            "2016-17",
            "2017-18",
            "2018-19",
            "2019-20",
        ),
        "West Ham United FC": ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"),
    },
    "Wigan Athletic": {"Wigan Athletic": ("2010-11", "2011-12", "2012-13")},
    "Wolverhampton Wanderers FC": {
        "Wolverhampton Wanderers": ("2010-11", "2011-12", "2018-19", "2019-20"),
        "Wolverhampton Wanderers FC": (
            "2020-21",
            "2021-22",
            "2022-23",
            "2023-24",
            "2024-25",
            "2025-26",
        ),
    },
}


CURRENT_FPL = {
    "AFC Bournemouth": ("3", "Bournemouth"),
    "Arsenal FC": ("1", "Arsenal"),
    "Aston Villa FC": ("2", "Aston Villa"),
    "Brentford FC": ("4", "Brentford"),
    "Brighton & Hove Albion FC": ("5", "Brighton"),
    "Chelsea FC": ("6", "Chelsea"),
    "Coventry City FC": ("7", "Coventry City"),
    "Crystal Palace FC": ("8", "Crystal Palace"),
    "Everton FC": ("9", "Everton"),
    "Fulham FC": ("10", "Fulham"),
    "Hull City AFC": ("11", "Hull City"),
    "Ipswich Town FC": ("12", "Ipswich Town"),
    "Leeds United FC": ("13", "Leeds"),
    "Liverpool FC": ("14", "Liverpool"),
    "Manchester City FC": ("15", "Man City"),
    "Manchester United FC": ("16", "Man Utd"),
    "Newcastle United FC": ("17", "Newcastle"),
    "Nottingham Forest FC": ("18", "Nott'm Forest"),
    "Sunderland AFC": ("20", "Sunderland"),
    "Tottenham Hotspur FC": ("19", "Spurs"),
}


def _source_snapshots() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_season, digest in SOURCE_HASHES.items():
        result.append(
            _reviewed(
                {
                    "commit_sha": SOURCE_COMMIT,
                    "content_sha256": digest,
                    "dataset_mode": "RECONSTRUCTED",
                    "path": f"{raw_season}/en.1.json",
                    "season_code": _season(raw_season),
                }
            )
        )
    return result


def _continuity_note(seasons: list[str]) -> str:
    positions = [list(SOURCE_HASHES).index(item.replace("/", "-")) for item in seasons]
    if any(right - left > 1 for left, right in pairwise(positions)):
        return "Canonical identity preserved across relegation and later Premier League return."
    if len(seasons) == 1:
        return "Single accepted Premier League corpus season; season membership is not identity."
    return "Continuous Premier League membership within the accepted corpus."


def build_identity_artifact() -> dict[str, Any]:
    snapshots = _source_snapshots()
    snapshot_by_season = {item["season_code"]: item for item in snapshots}
    clubs: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for canonical_name in sorted(CLUB_IDS):
        canonical_id = CLUB_IDS[canonical_name]
        raw_aliases = ALIASES[canonical_name]
        membership = sorted(
            {_season(season) for seasons in raw_aliases.values() for season in seasons}
        )
        identity_material = {
            "canonical_team_id": canonical_id,
            "entity_type": "TEAM",
            "id_generation_method": "NONDETERMINISTIC_UUIDV7_REGISTRATION",
            "registered_at": DECIDED_AT,
            "registration_authority": MAPPING_DECISION_ID,
        }
        identity_sha = _sha256(identity_material)
        external = None
        if canonical_name in CURRENT_FPL:
            external_id, display_name = CURRENT_FPL[canonical_name]
            external = {
                "external_id_text": external_id,
                "mapping_method": "MANUAL",
                "mapping_status": "HUMAN_VERIFIED",
                "observed_display_name": display_name,
                "provider_key": "official_fpl",
                "season_scope": "2026/27",
            }
        clubs.append(
            _reviewed(
                {
                    **identity_material,
                    "canonical_name": canonical_name,
                    "canonical_team_identity_sha256": identity_sha,
                    "continuity_note": _continuity_note(membership),
                    "current_fpl_external_identifier": external,
                    "evidence": [
                        MAPPING_DECISION_ID,
                        f"openfootball/football.json@{SOURCE_COMMIT}",
                        "CURRENT-TEAM-STRENGTH-001A-R reviewed identity table",
                    ],
                    "openfootball_aliases": sorted(raw_aliases),
                    "season_membership": membership,
                }
            )
        )
        for source_name, raw_seasons in sorted(raw_aliases.items()):
            season_scope = [_season(item) for item in raw_seasons]
            snapshot_hashes = [snapshot_by_season[item]["semantic_sha256"] for item in season_scope]
            source_material = {
                "competition": "English Premier League",
                "provider_key": "openfootball_football_json",
                "season_scope": season_scope,
                "source_team_name": source_name,
            }
            mappings.append(
                _reviewed(
                    {
                        "canonical_team_id": canonical_id,
                        "canonical_team_identity_sha256": identity_sha,
                        "decided_at": DECIDED_AT,
                        "evidence": [
                            f"openfootball/football.json@{SOURCE_COMMIT}:{item.replace('/', '-')}/en.1.json"
                            for item in season_scope
                        ],
                        "mapping_authority": MAPPING_AUTHORITY,
                        "mapping_decision_id": MAPPING_DECISION_ID,
                        "season_scope": season_scope,
                        "source_identity_sha256": _sha256(source_material),
                        "source_snapshot_identity": _sha256(snapshot_hashes),
                        "source_team_name": source_name,
                    }
                )
            )
    clubs.sort(key=lambda item: item["canonical_team_id"])
    mappings.sort(
        key=lambda item: (
            item["canonical_team_id"],
            item["source_team_name"],
            item["season_scope"],
        )
    )
    body = {
        "additional_alias_count": len(mappings) - len(clubs),
        "alias_count": len(mappings),
        "ambiguous_mapping_count": 0,
        "canonical_club_count": len(clubs),
        "canonical_clubs": clubs,
        "canonical_ordering": "canonical_team_id,source_team_name,season_scope",
        "competition": "English Premier League",
        "decided_at": DECIDED_AT,
        "mapping_authority": MAPPING_AUTHORITY,
        "mapping_decision_id": MAPPING_DECISION_ID,
        "provider_key": "openfootball_football_json",
        "record_count": len(mappings),
        "records": mappings,
        "schema_version": "openfootball-historical-team-identity-v1",
        "seasons_covered": [_season(item) for item in SOURCE_HASHES],
        "source_commit_sha": SOURCE_COMMIT,
        "source_snapshots": snapshots,
        "unresolved_club_count": 0,
    }
    return {**body, "root_semantic_sha256": _sha256(body)}


def build_governance_policy() -> dict[str, Any]:
    body = {
        "human_approval": {
            "approval_id": "CURRENT-TEAM-STRENGTH-001A#openfootball_football_json_team_strength_v1",
            "approved_at": DECIDED_AT,
            "approved_by": "Sebastian Greenhalgh",
            "rights_profile_id": "openfootball_football_json_team_strength_v1",
            "rights_profile_version": "1.0.0",
        },
        "materiality_policy": {
            "calibration_relative_harm_limit": "0.01",
            "player_xp_materiality_per_gw": "0.15",
            "production_promotion_requires_separate_human_approval": True,
            "prospective_min_gameweeks": 10,
            "prospective_min_labelled_fixtures": 100,
            "root_action_switch_always_material": True,
            "subgroup_relative_harm_limit": "0.01",
            "transfer_horizon_gameweeks": 3,
            "transfer_horizon_materiality_points": "0.50",
        },
        "model_implementation_present": False,
        "production_active": False,
        "schema_version": "current-team-strength-governance-v1",
        "selected_shadow_policy": {
            "attack_effective_prior_matches": 12,
            "decimal_boundary": "SERIALIZED_RATE_AND_ARTIFACT_ONLY",
            "defence_effective_prior_matches": 12,
            "entrant_policy": "HISTORICAL_PROMOTED_CLUB_COHORT_CENTRE",
            "fitting_algorithm": "FLOAT64_ANALYTIC_DAMPED_NEWTON",
            "half_life_days": 365,
            "home_advantage": "ONE_FITTED_GLOBAL_EFFECT",
            "maximum_output_rate": "8.000000",
            "model_family": "REGULARISED_TIME_WEIGHTED_INDEPENDENT_POISSON_TEAM_STRENGTH_V1",
            "parameter_uncertainty": {
                "covariance_retained": True,
                "hessian_retained": True,
                "plugin_prediction_status": "SHADOW_ONLY",
                "uncertainty_ticket_required_before_production": "CURRENT-TEAM-STRENGTH-001U",
            },
            "public_contract": "INDEPENDENT_POISSON_V1_SCORE_PRIOR_REQUEST_UNCHANGED",
            "training_evidence": "ALL_ELIGIBLE_RESULTS_STRICTLY_BEFORE_FORECAST_CUTOFF",
            "training_start_season": "2010/11",
        },
        "source_finality_policy": {
            "ambiguous_or_abandoned_action": "QUARANTINE_PENDING_GOVERNED_RESOLUTION",
            "correction_policy": "NEW_IMMUTABLE_DESCENDANT_NO_FROZEN_FORECAST_MUTATION",
            "eligibility_not_before": "00:00:00Z_ON_SOURCE_MATCH_DATE_PLUS_2_CALENDAR_DAYS",
            "live_required_conditions": [
                "IMMUTABLE_COMMIT_AND_VALIDATED_FILE_HASH",
                "RECEIVED_AND_VALIDATED_BEFORE_CUTOFF",
                "RECEIVED_AT_NO_LATER_THAN_CUTOFF",
                "USABLE_AT_NO_LATER_THAN_CUTOFF",
                "EXACTLY_ONE_CANONICAL_FIXTURE_AND_TWO_CANONICAL_CLUBS",
                "RECOGNIZED_FULL_TIME_SCORE",
                "NO_NON_FINAL_STATUS",
                "UNKNOWN_NONEMPTY_STATUS_QUARANTINED",
                "ELIGIBILITY_LAG_SATISFIED",
            ],
            "match_date_lag_calendar_days": 2,
            "postponed_policy": "REVISED_PLAYED_DATE_MUST_SATISFY_FULL_POLICY",
            "reconstructed_policy": "FINAL_CURRENT_VINTAGE_RECONSTRUCTED_ONLY_NO_HISTORICAL_AVAILABILITY_CLAIM",
            "same_day_use_allowed": False,
        },
        "source_freshness_policy": {
            "degraded": {
                "action": "RETAIN_LATEST_SEALED_ARTIFACT_WITH_VISIBLE_WARNING_NO_CURRENT_REFIT_CLAIM",
                "maximum_retrieval_age_hours_inclusive": 72,
                "minimum_retrieval_age_hours_exclusive": 24,
                "missing_due_must_equal": 0,
                "validation_must_pass": True,
            },
            "due_definition": "SCHEDULED_ROWS_WITH_ELIGIBILITY_NOT_BEFORE_NO_LATER_THAN_CUTOFF",
            "fresh": {
                "action": "TEAM_STRENGTH_REFIT_ALLOWED",
                "maximum_retrieval_age_hours_inclusive": 24,
                "missing_due_must_equal": 0,
                "validation_must_pass": True,
            },
            "missing_due_definition": "DUE_ROWS_WITHOUT_AN_ELIGIBLE_FINAL_SCORE",
            "repository_commit_age_alone_defines_freshness": False,
            "retrieval_age_definition": "CUTOFF_MINUS_LATEST_SUCCESSFUL_USABLE_OPENFOOTBALL_SNAPSHOT_RETRIEVAL",
            "stale_blocked": {
                "action": "NO_NEW_CURRENT_ARTIFACT_USE_GOVERNED_LEAGUE_PRIOR_FALLBACK_IF_LEGAL",
                "any_condition": [
                    "MISSING_DUE_GREATER_THAN_ZERO",
                    "RETRIEVAL_AGE_GREATER_THAN_72_HOURS",
                    "UNRESOLVED_CANONICAL_MAPPING",
                    "AMBIGUOUS_STATUS",
                    "INVALID_SCHEMA",
                    "INVALID_SOURCE_LINEAGE",
                ],
            },
        },
        "statistical_research_evidence": {
            "baseline_exact_score_log_loss": "2.951989",
            "bootstrap_block": "GAMEWEEK",
            "candidate_minus_baseline": "-0.064172",
            "classification": "RECONSTRUCTED_OUT_OF_TIME_SHADOW_EVIDENCE",
            "confidence_interval_95": ["-0.100400", "-0.028708"],
            "production_superiority_claimed": False,
            "selected_exact_score_log_loss": "2.887816",
        },
        "status": "GOVERNANCE_ONLY_NO_MODEL_IMPLEMENTATION",
        "ticket_id": "CURRENT-TEAM-STRENGTH-001A-P0",
    }
    return {**body, "semantic_sha256": _sha256(body)}


def build_identity_review(identity: dict[str, Any]) -> str:
    lines = [
        "# CURRENT-TEAM-STRENGTH-001A-P0 canonical identity review",
        "",
            f"- Decision: `{MAPPING_DECISION_ID}`",
            f"- Decided by: `{MAPPING_AUTHORITY}`",
            f"- Decided at: `{DECIDED_AT}`",
            f"- Source commit: `{SOURCE_COMMIT}`",
        "",
        "| Canonical club | Canonical UUIDv7 | Exact OpenFootball aliases | Seasons | Current FPL external ID | Continuity | Evidence |",
        "|---|---|---|---|---|---|---|",
    ]
    for club in sorted(identity["canonical_clubs"], key=lambda item: item["canonical_name"]):
        external = club["current_fpl_external_identifier"]
        external_text = (
            f"2026/27 `{external['external_id_text']}` ({external['observed_display_name']})"
            if external is not None
            else "—"
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    club["canonical_name"],
                    f"`{club['canonical_team_id']}`",
                    "<br>".join(f"`{value}`" for value in club["openfootball_aliases"]),
                    ", ".join(club["season_membership"]),
                    external_text,
                    club["continuity_note"],
                    f"P0 human review; OpenFootball `{SOURCE_COMMIT[:12]}`",
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Repository inspection found no pre-existing governed club registry to reuse. These",
            "are the minimum one-time nondeterministic UUIDv7 canonical TEAM registrations under",
            "the existing canonical-entity identity rule; no database mutation is performed by P0.",
            "",
            "## Review result",
            "",
            f"- canonical clubs: `{identity['canonical_club_count']}`",
            f"- accepted source alias records: `{identity['record_count']}`",
            f"- accepted source aliases: `{identity['alias_count']}`",
            f"- additional spelling variants: `{identity['additional_alias_count']}`",
            f"- seasons: `{len(identity['seasons_covered'])}`",
            f"- unresolved clubs: `{identity['unresolved_club_count']}`",
            f"- ambiguous mappings: `{identity['ambiguous_mapping_count']}`",
            f"- root semantic SHA-256: `{identity['root_semantic_sha256']}`",
            "",
            "All mappings are explicit human-reviewed registrations. Names and current FPL IDs are",
            "evidence/external identifiers only; neither is canonical identity. No fuzzy matching is",
            "authorized.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    identity = build_identity_artifact()
    policy = build_governance_policy()
    outputs = {
        ROOT / "config/providers/openfootball_historical_team_identity.json": _pretty(identity),
        ROOT / "config/models/current_team_strength_governance.json": _pretty(policy),
        ROOT
        / "evidence/tickets/CURRENT-TEAM-STRENGTH-001A-P0/IDENTITY_REVIEW.md": build_identity_review(
            identity
        ),
    }
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(path.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
