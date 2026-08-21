"""Transient GW1 current-catalogue bridge tests; all input material is synthetic."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.availability.current import current_player_id, current_team_id
from dmf_pulse.ingestion.errors import IngestionError
from dmf_pulse.ingestion.fpl.current import CurrentFplInputRequest, CurrentFplInputService
from dmf_pulse.player_evidence.approvals import (
    POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
    SECOND_RETRY_APPROVAL_SHA256,
    load_player_history_rights_approval,
    validate_post_diagnostic_capture_authorization,
    validate_second_retry_capture_authorization,
)
from dmf_pulse.player_evidence.catalogue import build_current_player_history_catalogue
from dmf_pulse.player_evidence.empirical_bayes import compile_posterior_artifact
from dmf_pulse.player_evidence.history import ApprovedCaptureRequest, validate_capture_request
from dmf_pulse.player_evidence.models import CurrentPlayerIdentityMode, RetentionMode
from dmf_pulse.player_evidence.profiles import build_allocation_candidate
from tests.unit.player_evidence.support import eb_parameters, generic_prior, price_policy

CAPTURED = datetime(2026, 8, 18, 12, tzinfo=UTC)
RECEIVED = datetime(2026, 8, 18, 12, 5, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
RIGHTS_APPROVAL_SHA256 = "d946552f2a55df7ed400bb43cff6bf85b4bdf8cbfe804044d08d9c9a96f8e2fd"
SECOND_RETRY_CATALOGUE_SHA256 = "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
POST_DIAGNOSTIC_APPROVAL_PATH = (
    "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_POST_DIAGNOSTIC_FULL_CAPTURE_APPROVAL.json"
)


def _source(repository_root: Path, name: str) -> object:
    return json.loads(
        (repository_root / "fixtures/fpl/FPL-004/happy_path" / name).read_text(encoding="utf-8")
    )


def _bundle(repository_root: Path, tmp_path: Path, *, bootstrap: object | None = None):
    bootstrap_value = _source(repository_root, "bootstrap.json") if bootstrap is None else bootstrap
    fixtures_value = _source(repository_root, "fixtures.json")
    tmp_path.mkdir(parents=True, exist_ok=True)
    bootstrap_path = tmp_path / "manual-bootstrap.json"
    fixtures_path = tmp_path / "manual-fixtures.json"
    bootstrap_path.write_text(json.dumps(bootstrap_value), encoding="utf-8")
    fixtures_path.write_text(json.dumps(fixtures_value), encoding="utf-8")
    request = CurrentFplInputRequest(
        bootstrap_path=bootstrap_path,
        fixtures_path=fixtures_path,
        competition_key="PL",
        season_code="2026/27",
        captured_at=CAPTURED,
        information_cutoff=CUTOFF,
        rights_profile_id="fpl_official_private_manual_v1",
        gameweek=1,
    )
    return CurrentFplInputService(clock=lambda: RECEIVED).compile(request)


def test_current_catalogue_uses_exact_stage7_transient_identities_and_source_lineage(
    repository_root: Path, tmp_path: Path
) -> None:
    bundle = _bundle(repository_root, tmp_path)
    stage7_team_ids = {team.provider_team_id: current_team_id(team) for team in bundle.teams}

    catalogue = build_current_player_history_catalogue(bundle, stage7_team_ids=stage7_team_ids)

    assert catalogue.identity_mode is CurrentPlayerIdentityMode.GW1_STAGE7_TRANSIENT_SURROGATE
    assert catalogue.source_bundle_semantic_sha256 == bundle.semantic_sha256
    assert catalogue.source_bootstrap_semantic_sha256 == bundle.provenance.bootstrap_semantic_sha256
    assert catalogue.semantic_sha256 is not None
    assert len(catalogue.players) == len(bundle.players)
    assert [row.player_id for row in catalogue.players] == sorted(
        (row.player_id for row in catalogue.players), key=str
    )
    assert len({row.source_player_id for row in catalogue.players}) == len(bundle.players)

    by_source_id = {row.source_player_id: row for row in catalogue.players}
    team_by_digest = {team.identity.canonical_lookup_sha256: team for team in bundle.teams}
    for player in bundle.players:
        row = by_source_id[player.provider_element_id]
        team = team_by_digest[player.team_identity.canonical_lookup_sha256]
        assert row.player_id == current_player_id(player)
        assert row.team_id == current_team_id(team)
        assert row.position == player.position
        assert row.current_price_tenths == player.current_price_tenths
        assert row.source_player_identity_sha256 == player.identity.canonical_lookup_sha256
        assert row.source_team_identity_sha256 == team.identity.canonical_lookup_sha256

    rendered = catalogue.model_dump_json()
    assert "A. Keeper" not in rendered
    assert "web_name" not in rendered
    assert "first_name" not in rendered
    assert "second_name" not in rendered


def test_catalogue_is_deterministic_and_identity_is_not_derived_from_names(
    repository_root: Path, tmp_path: Path
) -> None:
    original = _bundle(repository_root, tmp_path / "original")
    original_catalogue = build_current_player_history_catalogue(original)
    changed_name = _source(repository_root, "bootstrap.json")
    assert isinstance(changed_name, dict)
    elements = changed_name["elements"]
    assert isinstance(elements, list)
    assert isinstance(elements[0], dict)
    elements[0]["web_name"] = "Not An Identity"
    renamed = _bundle(repository_root, tmp_path / "renamed", bootstrap=changed_name)
    renamed_catalogue = build_current_player_history_catalogue(renamed)
    assert [row.player_id for row in renamed_catalogue.players] == [
        row.player_id for row in original_catalogue.players
    ]

    changed_identity = deepcopy(_source(repository_root, "bootstrap.json"))
    assert isinstance(changed_identity, dict)
    changed_elements = changed_identity["elements"]
    assert isinstance(changed_elements, list)
    assert isinstance(changed_elements[0], dict)
    changed_elements[0]["id"] = int(changed_elements[0]["id"]) + 1000
    identity_changed = _bundle(
        repository_root, tmp_path / "identity-changed", bootstrap=changed_identity
    )
    changed_catalogue = build_current_player_history_catalogue(identity_changed)
    assert original_catalogue.semantic_sha256 != changed_catalogue.semantic_sha256
    assert {row.player_id for row in original_catalogue.players} != {
        row.player_id for row in changed_catalogue.players
    }


def test_stage7_team_context_mismatch_fails_closed(repository_root: Path, tmp_path: Path) -> None:
    bundle = _bundle(repository_root, tmp_path)
    team_ids = {team.provider_team_id: current_team_id(team) for team in bundle.teams}
    first_team_id = min(team_ids)
    team_ids[first_team_id] = next(value for key, value in team_ids.items() if key != first_team_id)

    with pytest.raises(IngestionError) as raised:
        build_current_player_history_catalogue(bundle, stage7_team_ids=team_ids)
    assert raised.value.code == "MAPPING_CONFLICT"


def test_catalogue_stays_in_memory_and_stage9_profiles_keep_stage7_ids(
    repository_root: Path, tmp_path: Path
) -> None:
    bundle = _bundle(repository_root, tmp_path)
    catalogue = build_current_player_history_catalogue(bundle)
    assert "path" not in build_current_player_history_catalogue.__annotations__

    posterior = compile_posterior_artifact(
        catalogue=catalogue,
        histories=(),
        role_priors=(generic_prior(),),
        tactical_roles={},
        parameters=eb_parameters(),
        information_cutoff=CUTOFF,
        source_observed_at=RECEIVED,
        usable_at=RECEIVED,
        produced_at=RECEIVED,
        source_locator="synthetic://GW1-PLY-003/current-catalogue-bridge",
        schema_fingerprint="a" * 64,
        rights_profile_id="SYNTHETIC_TEST_ONLY",
    )
    allocation = build_allocation_candidate(
        catalogue=catalogue,
        posterior=posterior,
        role_priors=(generic_prior(),),
        tactical_roles={},
        information_cutoff=CUTOFF,
        price_policy=price_policy(),
        degraded_player_allocation=False,
    )
    assert {profile.player_id for profile in allocation.profiles} == {
        str(row.player_id) for row in catalogue.players
    }
    assert {profile.team_id for profile in allocation.profiles} == {
        str(row.team_id) for row in catalogue.players
    }


def test_accepted_v2_rights_loader_accepts_only_the_exact_approved_scope(
    repository_root: Path, tmp_path: Path
) -> None:
    path = repository_root / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_RIGHTS_APPROVAL.json"
    approval = load_player_history_rights_approval(
        path, expected_approval_sha256=RIGHTS_APPROVAL_SHA256
    )
    assert approval.governance_approval_sha256 == RIGHTS_APPROVAL_SHA256
    assert approval.maximum_player_requests == 650
    assert approval.raw_retention == "FORBIDDEN"

    altered = json.loads(path.read_text(encoding="utf-8"))
    altered["scope"] = "NOT_PRIVATE"
    altered_path = tmp_path / "altered-rights.json"
    altered_path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_player_history_rights_approval(
            altered_path, expected_approval_sha256=RIGHTS_APPROVAL_SHA256
        )
    assert raised.value.code == "RIGHTS_APPROVAL_INVALID"


def test_accepted_v2_rights_loader_binds_the_existing_capture_guard(
    repository_root: Path, tmp_path: Path
) -> None:
    path = repository_root / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_RIGHTS_APPROVAL.json"
    approval = load_player_history_rights_approval(
        path, expected_approval_sha256=RIGHTS_APPROVAL_SHA256
    )
    catalogue = build_current_player_history_catalogue(_bundle(repository_root, tmp_path))
    request = ApprovedCaptureRequest(
        approval=approval,
        expected_approval_sha256=RIGHTS_APPROVAL_SHA256,
        catalogue=catalogue,
        information_cutoff=CUTOFF,
        maximum_player_count=len(catalogue.players),
        terms_fingerprint="ad62cb745459df3282f8900117b85352a01d75754e080d06aa3836dcd2b2b246",
        retention_mode=RetentionMode.POSTERIOR_ONLY,
    )
    validate_capture_request(request)

    with pytest.raises(IngestionError) as raised:
        validate_capture_request(
            ApprovedCaptureRequest(
                approval=approval,
                expected_approval_sha256="0" * 64,
                catalogue=catalogue,
                information_cutoff=CUTOFF,
                maximum_player_count=len(catalogue.players),
                terms_fingerprint=approval.terms_fingerprint,
            )
        )
    assert raised.value.code == "RIGHTS_APPROVAL_HASH_MISMATCH"


def test_second_retry_loader_accepts_only_the_exact_new_human_directive(
    repository_root: Path,
) -> None:
    first_path = (
        repository_root / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_RIGHTS_APPROVAL.json"
    )
    second_path = (
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_SECOND_RETRY_RIGHTS_APPROVAL.json"
    )
    historical = load_player_history_rights_approval(
        first_path, expected_approval_sha256=RIGHTS_APPROVAL_SHA256
    )
    retry = load_player_history_rights_approval(
        second_path, expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256
    )
    assert historical.governance_approval_sha256 == RIGHTS_APPROVAL_SHA256
    assert retry.governance_approval_sha256 == SECOND_RETRY_APPROVAL_SHA256
    assert retry.maximum_player_requests == 599

    with pytest.raises(IngestionError) as raised:
        validate_second_retry_capture_authorization(
            historical,
            expected_approval_sha256=RIGHTS_APPROVAL_SHA256,
            catalogue_semantic_sha256=SECOND_RETRY_CATALOGUE_SHA256,
        )
    assert raised.value.code == "RIGHTS_APPROVAL_HASH_MISMATCH"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda record: record.__setitem__("required_capture_code_sha", "0" * 40),
        lambda record: record.__setitem__("previous_consumed_approval_sha256", "1" * 64),
        lambda record: record.__setitem__("expected_catalogue_semantic_sha256", "2" * 64),
        lambda record: record["capture_constraints"].__setitem__("maximum_player_requests", 600),
        lambda record: record["terms_review"].__setitem__("snapshot_sha256", "3" * 64),
    ),
)
def test_second_retry_loader_rejects_any_altered_governance_field(
    repository_root: Path, tmp_path: Path, mutate
) -> None:
    source = (
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_SECOND_RETRY_RIGHTS_APPROVAL.json"
    )
    altered = json.loads(source.read_text(encoding="utf-8"))
    mutate(altered)
    altered_path = tmp_path / "altered-second-retry.json"
    altered_path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_player_history_rights_approval(
            altered_path, expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256
        )
    assert raised.value.code == "RIGHTS_APPROVAL_INVALID"


def test_second_retry_loader_rejects_wrong_hash_and_self_consistent_third_record(
    repository_root: Path, tmp_path: Path
) -> None:
    source = (
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_SECOND_RETRY_RIGHTS_APPROVAL.json"
    )
    with pytest.raises(IngestionError) as wrong_hash:
        load_player_history_rights_approval(source, expected_approval_sha256="0" * 64)
    assert wrong_hash.value.code == "RIGHTS_APPROVAL_HASH_MISMATCH"

    third = json.loads(source.read_text(encoding="utf-8"))
    third["retry_ordinal"] = 3
    third_without_hash = dict(third)
    third_without_hash.pop("approval_sha256")
    third["approval_sha256"] = canonical_sha256(third_without_hash)
    third_path = tmp_path / "self-consistent-third.json"
    third_path.write_text(json.dumps(third), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_player_history_rights_approval(
            third_path, expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256
        )
    assert raised.value.code == "RIGHTS_APPROVAL_INVALID"


def test_second_retry_catalogue_guard_rejects_drift_and_request_bound() -> None:
    approval_path = Path(
        "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_SECOND_RETRY_RIGHTS_APPROVAL.json"
    )
    approval = load_player_history_rights_approval(
        approval_path, expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256
    )
    with pytest.raises(IngestionError) as wrong_catalogue:
        validate_second_retry_capture_authorization(
            approval,
            expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256,
            catalogue_semantic_sha256="0" * 64,
        )
    assert wrong_catalogue.value.code == "CATALOGUE_HASH_MISMATCH"
    altered = approval.model_copy(update={"maximum_player_requests": 600})
    with pytest.raises(IngestionError) as invalid_bound:
        validate_second_retry_capture_authorization(
            altered,
            expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256,
            catalogue_semantic_sha256=SECOND_RETRY_CATALOGUE_SHA256,
        )
    assert invalid_bound.value.code == "REQUEST_BOUND_INVALID"


def test_second_retry_terms_mismatch_blocks_before_transport(
    repository_root: Path, tmp_path: Path
) -> None:
    approval_path = (
        repository_root
        / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_SECOND_RETRY_RIGHTS_APPROVAL.json"
    )
    approval = load_player_history_rights_approval(
        approval_path, expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256
    )
    catalogue = build_current_player_history_catalogue(_bundle(repository_root, tmp_path))
    with pytest.raises(IngestionError) as raised:
        validate_capture_request(
            ApprovedCaptureRequest(
                approval=approval,
                expected_approval_sha256=SECOND_RETRY_APPROVAL_SHA256,
                catalogue=catalogue,
                information_cutoff=CUTOFF,
                maximum_player_count=len(catalogue.players),
                terms_fingerprint="0" * 64,
                retention_mode=RetentionMode.POSTERIOR_ONLY,
            )
        )
    assert raised.value.code == "TERMS_FINGERPRINT_DRIFT"


def test_v4_loader_and_full_universe_guard_accept_only_the_new_directive(
    repository_root: Path,
) -> None:
    v4 = load_player_history_rights_approval(
        repository_root / POST_DIAGNOSTIC_APPROVAL_PATH,
        expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
    )
    assert v4.governance_approval_sha256 == POST_DIAGNOSTIC_FULL_APPROVAL_SHA256
    assert v4.maximum_player_requests == 599
    assert v4.raw_retention == "FORBIDDEN"
    assert v4.derived_retention is RetentionMode.POSTERIOR_ONLY
    validate_post_diagnostic_capture_authorization(
        v4,
        expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
        catalogue_semantic_sha256=SECOND_RETRY_CATALOGUE_SHA256,
        maximum_player_count=599,
    )

    for path, approval_sha256 in (
        (
            repository_root
            / "evidence/tickets/GW1-PLY-003/GW1_PLAYER_HISTORY_RIGHTS_APPROVAL.json",
            RIGHTS_APPROVAL_SHA256,
        ),
        (
            repository_root / "evidence/tickets/GW1-PLY-003/"
            "GW1_PLAYER_HISTORY_SECOND_RETRY_RIGHTS_APPROVAL.json",
            SECOND_RETRY_APPROVAL_SHA256,
        ),
    ):
        consumed = load_player_history_rights_approval(
            path, expected_approval_sha256=approval_sha256
        )
        with pytest.raises(IngestionError) as raised:
            validate_post_diagnostic_capture_authorization(
                consumed,
                expected_approval_sha256=approval_sha256,
                catalogue_semantic_sha256=SECOND_RETRY_CATALOGUE_SHA256,
                maximum_player_count=599,
            )
        assert raised.value.code == "RIGHTS_APPROVAL_HASH_MISMATCH"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda record: record.__setitem__("diagnostic_result_sha256", "0" * 64),
        lambda record: record.__setitem__("required_remediation_sha", "1" * 40),
        lambda record: record.__setitem__("expected_catalogue_semantic_sha256", "2" * 64),
        lambda record: record["capture_constraints"].__setitem__("maximum_player_requests", 600),
        lambda record: record["terms_review"].__setitem__("snapshot_sha256", "3" * 64),
        lambda record: record.__setitem__("raw_retention", "PERMITTED"),
        lambda record: record.__setitem__("derived_retention", "RAW"),
    ),
)
def test_v4_loader_rejects_every_altered_governance_field(
    repository_root: Path, tmp_path: Path, mutate
) -> None:
    source = repository_root / POST_DIAGNOSTIC_APPROVAL_PATH
    altered = json.loads(source.read_text(encoding="utf-8"))
    mutate(altered)
    altered_path = tmp_path / "altered-v4.json"
    altered_path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(IngestionError) as raised:
        load_player_history_rights_approval(
            altered_path, expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256
        )
    assert raised.value.code == "RIGHTS_APPROVAL_INVALID"


def test_v4_rejects_self_consistent_fifth_record_and_runtime_universe_drift(
    repository_root: Path, tmp_path: Path
) -> None:
    source = repository_root / POST_DIAGNOSTIC_APPROVAL_PATH
    fifth = json.loads(source.read_text(encoding="utf-8"))
    fifth["schema_version"] = "gw1-player-history-rights-approval-v5"
    without_hash = dict(fifth)
    without_hash.pop("approval_sha256")
    fifth["approval_sha256"] = canonical_sha256(without_hash)
    fifth_path = tmp_path / "self-consistent-v5.json"
    fifth_path.write_text(json.dumps(fifth), encoding="utf-8")
    with pytest.raises(IngestionError) as future:
        load_player_history_rights_approval(
            fifth_path, expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256
        )
    assert future.value.code == "RIGHTS_APPROVAL_INVALID"

    v4 = load_player_history_rights_approval(
        source, expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256
    )
    with pytest.raises(IngestionError) as catalogue_drift:
        validate_post_diagnostic_capture_authorization(
            v4,
            expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
            catalogue_semantic_sha256="4" * 64,
            maximum_player_count=599,
        )
    assert catalogue_drift.value.code == "CATALOGUE_HASH_MISMATCH"
    with pytest.raises(IngestionError) as count_drift:
        validate_post_diagnostic_capture_authorization(
            v4,
            expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
            catalogue_semantic_sha256=SECOND_RETRY_CATALOGUE_SHA256,
            maximum_player_count=600,
        )
    assert count_drift.value.code == "REQUEST_BOUND_INVALID"


def test_v4_terms_and_retention_drift_fail_capture_request(
    repository_root: Path, tmp_path: Path
) -> None:
    v4 = load_player_history_rights_approval(
        repository_root / POST_DIAGNOSTIC_APPROVAL_PATH,
        expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
    )
    catalogue = build_current_player_history_catalogue(_bundle(repository_root, tmp_path))
    for terms, retention, expected_code in (
        ("0" * 64, RetentionMode.POSTERIOR_ONLY, "TERMS_FINGERPRINT_DRIFT"),
        (v4.terms_fingerprint, "RAW", "RAW_RETENTION_FORBIDDEN"),
    ):
        with pytest.raises(IngestionError) as raised:
            validate_capture_request(
                ApprovedCaptureRequest(
                    approval=v4,
                    expected_approval_sha256=POST_DIAGNOSTIC_FULL_APPROVAL_SHA256,
                    catalogue=catalogue,
                    information_cutoff=CUTOFF,
                    maximum_player_count=len(catalogue.players),
                    terms_fingerprint=terms,
                    retention_mode=retention,  # type: ignore[arg-type]
                )
            )
        assert raised.value.code == expected_code
