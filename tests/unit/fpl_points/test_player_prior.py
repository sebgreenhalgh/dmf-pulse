from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.player_prior import (
    build_player_prior_identity_binding,
    load_packaged_player_prior,
    parse_player_prior,
    parse_player_prior_acceptance,
)
from dmf_pulse.ingestion.fpl.current import (
    CurrentFplInputRequest,
    CurrentFplInputService,
)

_NAMESPACE = UUID("7151293c-5b5d-5cc3-9689-c4e728ea8b55")
_VERSION = "gw1-current-availability-stage7-v1"
_CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def _source(root: Path, name: str) -> object:
    return json.loads((root / "fixtures/fpl/FPL-004/happy_path" / name).read_text("utf-8"))


def _lookup_sha(entity_type: str, namespace: str, external_id: int) -> str:
    return canonical_sha256(
        {
            "entity_type": entity_type,
            "external_id_text": str(external_id),
            "identifier_namespace": namespace,
            "provider_key": "official_fpl",
            "provider_product": "fantasy_premierleague",
            "season_code": "2026/27",
        }
    )


def _donor_id(kind: str, identity_sha256: str) -> str:
    return str(uuid5(_NAMESPACE, "\x1f".join((_VERSION, kind, identity_sha256))))


def _build_current_fpl(root: Path, tmp_path: Path):
    prior = load_packaged_player_prior()
    lineages = {lineage.player_id: lineage for lineage in prior.artifact.lineage}
    donor_team_by_source = {
        source_id: _donor_id("team", _lookup_sha("TEAM", "fpl.team.id", source_id))
        for source_id in (1, 2)
    }
    selected: list[tuple[int, int, bool]] = []
    for source_team_id, donor_team_id in donor_team_by_source.items():
        candidates = [
            profile for profile in prior.artifact.profiles if profile.team_id == donor_team_id
        ][:2]
        assert len(candidates) == 2
        selected.extend(
            (
                lineages[profile.player_id].source_player_id,
                source_team_id,
                profile.goalkeeper_saves_per90 > 0.0,
            )
            for profile in candidates
        )

    bootstrap = _source(root, "bootstrap.json")
    fixtures = _source(root, "fixtures.json")
    assert isinstance(bootstrap, dict)
    assert isinstance(fixtures, list)
    templates = {int(item["element_type"]): item for item in bootstrap["elements"]}
    players = []
    for offset, (source_player_id, source_team_id, is_goalkeeper) in enumerate(selected):
        element_type = 1 if is_goalkeeper else 2
        player = deepcopy(templates[element_type])
        player.update(
            {
                "id": source_player_id,
                "code": 700000 + offset,
                "team": source_team_id,
                "element_type": element_type,
                "first_name": f"Synthetic{offset}",
                "second_name": f"Prior{offset}",
                "web_name": f"PP{offset}",
                "status": "a",
                "chance_of_playing_this_round": None,
                "chance_of_playing_next_round": None,
                "news": "",
                "news_added": None,
            }
        )
        players.append(player)
    bootstrap["elements"] = players
    bootstrap_path = tmp_path / "bootstrap.json"
    fixtures_path = tmp_path / "fixtures.json"
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures), encoding="utf-8")
    clock = iter(
        (
            datetime(2026, 8, 21, 17, 10, tzinfo=UTC),
            datetime(2026, 8, 21, 17, 11, tzinfo=UTC),
        )
    )
    bundle = CurrentFplInputService(clock=lambda: next(clock)).compile(
        CurrentFplInputRequest(
            bootstrap_path=bootstrap_path,
            fixtures_path=fixtures_path,
            competition_key="PL",
            season_code="2026/27",
            target_gameweek=1,
            captured_at=datetime(2026, 8, 21, 17, 0, tzinfo=UTC),
            information_cutoff=_CUTOFF,
            rights_profile_id="fpl_official_private_manual_v1",
        )
    )
    return bundle, tuple(item[0] for item in selected)


def _prior_payload() -> dict[str, object]:
    prior = load_packaged_player_prior()
    return prior.artifact.model_dump(mode="json")


def test_packaged_accepted_private_prior_loads_with_exact_lineage() -> None:
    left = load_packaged_player_prior()
    right = load_packaged_player_prior()

    assert left == right
    assert len(left.artifact.profiles) == len(left.artifact.lineage) == 599
    assert left.artifact.artifact_sha256 == (
        "629d6c288f9faa7aa7763f5c578e662511c03d514169f683cbeb6ee81af695be"
    )
    assert left.historical_acceptance.acceptance_sha256 == (
        "39737c6b96e2664f63f19b4ea0c34038d7c0ec5d9afc9f60cc1c6b89749a3352"
    )
    assert left.historical_acceptance.production_activation is False
    assert left.artifact.status == "CANDIDATE_NOT_ACCEPTED"
    assert left.historical_acceptance.status == "HUMAN_ACCEPTED_PRIVATE_GW1_ONLY"
    assert (
        canonical_sha256(left.artifact.model_dump(mode="json", exclude={"artifact_sha256"}))
        == left.artifact.artifact_sha256
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.__setitem__("schema_version", "unknown-v2"), "PLAYER_PRIOR_INVALID"),
        (
            lambda value: value["profiles"][0].__setitem__("goal_share", 0.999),
            "PLAYER_PRIOR_INVALID",
        ),
        (
            lambda value: value["profiles"].append(deepcopy(value["profiles"][0])),
            "PLAYER_PRIOR_INVALID",
        ),
        (
            lambda value: value["profiles"][0].__setitem__("player_id", "not-a-uuid"),
            "PLAYER_PRIOR_INVALID",
        ),
    ],
)
def test_prior_schema_hash_duplicates_and_ids_fail_closed(mutation, code: str) -> None:
    payload = _prior_payload()
    mutation(payload)
    with pytest.raises(FplPointsError) as caught:
        parse_player_prior(payload)
    assert caught.value.code == code


def test_malformed_prior_and_tampered_acceptance_fail_closed() -> None:
    with pytest.raises(FplPointsError) as malformed:
        parse_player_prior(b"{")
    assert malformed.value.code == "PLAYER_PRIOR_INVALID"

    acceptance = load_packaged_player_prior().historical_acceptance.model_dump(mode="json")
    acceptance["production_activation"] = True
    with pytest.raises(FplPointsError) as tampered:
        parse_player_prior_acceptance(acceptance)
    assert tampered.value.code == "PLAYER_PRIOR_ACCEPTANCE_INVALID"


def test_current_fpl_identity_binding_is_exact_and_deterministic(
    repository_root: Path, tmp_path: Path
) -> None:
    prior = load_packaged_player_prior()
    current_fpl, source_ids = _build_current_fpl(repository_root, tmp_path)
    current_player_ids = {
        source_id: f"00000000-0000-4000-8000-{index:012d}"
        for index, source_id in enumerate(source_ids, start=1)
    }
    current_team_ids = {
        source_id: f"10000000-0000-4000-8000-{source_id:012d}" for source_id in (1, 2)
    }

    left = build_player_prior_identity_binding(
        prior,
        current_fpl,
        canonical_player_ids_by_source_id=current_player_ids,
        canonical_team_ids_by_source_id=current_team_ids,
    )
    right = build_player_prior_identity_binding(
        prior,
        current_fpl,
        canonical_player_ids_by_source_id=dict(reversed(tuple(current_player_ids.items()))),
        canonical_team_ids_by_source_id=dict(reversed(tuple(current_team_ids.items()))),
    )

    assert left == right
    assert tuple(entry.current_player_id for entry in left.entries) == tuple(
        sorted(current_player_ids.values())
    )
    assert left.source_bundle_sha256 == current_fpl.semantic_sha256


def test_identity_binding_rejects_missing_duplicate_and_stale_team(
    repository_root: Path, tmp_path: Path
) -> None:
    prior = load_packaged_player_prior()
    current_fpl, source_ids = _build_current_fpl(repository_root, tmp_path)
    players = {
        source_id: f"20000000-0000-4000-8000-{index:012d}"
        for index, source_id in enumerate(source_ids, start=1)
    }
    teams = {source_id: f"30000000-0000-4000-8000-{source_id:012d}" for source_id in (1, 2)}

    missing = dict(players)
    missing[999999] = "20000000-0000-4000-8000-999999999999"
    with pytest.raises(FplPointsError) as missing_error:
        build_player_prior_identity_binding(
            prior,
            current_fpl,
            canonical_player_ids_by_source_id=missing,
            canonical_team_ids_by_source_id=teams,
        )
    assert missing_error.value.code == "PLAYER_PRIOR_MISSING"

    duplicate = dict(players)
    duplicate[source_ids[1]] = duplicate[source_ids[0]]
    with pytest.raises(FplPointsError) as duplicate_error:
        build_player_prior_identity_binding(
            prior,
            current_fpl,
            canonical_player_ids_by_source_id=duplicate,
            canonical_team_ids_by_source_id=teams,
        )
    assert duplicate_error.value.code == "PLAYER_IDENTITY_MISMATCH"

    first = current_fpl.players[0]
    changed = first.model_copy(
        update={
            "team_identity": current_fpl.teams[
                1 if first.team_identity.external_id_text == "1" else 0
            ].identity
        }
    )
    tampered_bundle = current_fpl.model_copy(
        update={"players": (changed, *current_fpl.players[1:])}
    )
    with pytest.raises(FplPointsError) as stale_error:
        build_player_prior_identity_binding(
            prior,
            tampered_bundle,
            canonical_player_ids_by_source_id=players,
            canonical_team_ids_by_source_id=teams,
        )
    assert stale_error.value.code == "PLAYER_IDENTITY_MISMATCH"
