"""Canonical authority and all-ten admission without scoring hypothetical P01 labels."""

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dmf_pulse.cli.recovery import recovery_app
from dmf_pulse.evaluation import p01_canonical as c
from dmf_pulse.ingestion.openfootball.team_strength_data import StrengthEvidenceError, seal
from tests.unit.evaluation.p01_canonical_support import AT, owned_snapshot, owned_view

pytestmark = pytest.mark.unit


def test_proposal_preserves_original_identity_without_accepting_it():
    identity, proposal = c.original_identity(), c.propose_canonical_binding()
    assert identity.forecast_sha256 == proposal.forecast_sha256 == c.FORECAST_SHA
    assert len(identity.fixtures) == 10 and identity.dataset_mode == "LIVE_OBSERVED"
    assert proposal.state == "PROPOSED_UNACCEPTED" and not proposal.acquisition_authorized
    assert len(
        proposal.components
    ) > 400 and proposal.historical_original_protocol_sha256.startswith("93b9c2")
    assert c.installed_canonical_acceptances().accepted_code_bindings == ()


def test_empty_authority_denies_before_reading_inputs_or_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(
        c, "_regular_or_none", lambda *args, **kwargs: pytest.fail("unaccepted input read")
    )
    monkeypatch.setattr(
        c, "score_public_fixture_labels", lambda *args, **kwargs: pytest.fail("unaccepted metric")
    )
    with pytest.raises(StrengthEvidenceError, match="CODE_BINDING_NOT_ACCEPTED"):
        c.score_original_p01(tmp_path / "forecast", tmp_path / "outcomes", as_of=AT)


def test_complete_ten_owned_admission_never_calls_a_metric(monkeypatch):
    monkeypatch.setattr(
        c,
        "score_public_fixture_labels",
        lambda *args, **kwargs: pytest.fail("admission calculated metric"),
    )
    view = owned_view()
    labels = c.admit_canonical_labels(view, owned_snapshot(view), as_of=AT)
    assert len(labels) == len({row.fixture_id for row in labels}) == 10
    assert view.dataset_mode == "RECONSTRUCTED" and view.semantic_sha256 != c.FORECAST_SHA
    assert {row.fixture_id for row in labels}.isdisjoint(
        {row.fixture.fixture_id for row in c.original_identity().fixtures}
    )


@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "registry",
        "not_final",
        "partial",
        "unsupported",
        "bool",
        "string",
        "negative",
        "before_lag",
        "freeze_day",
        "future_played",
        "orientation",
        "non_view",
    ],
)
def test_all_ten_owned_admission_fails_closed(attack):
    view = owned_view()
    changes, kwargs, at = {}, {}, AT
    if attack == "missing":
        kwargs["omit_last"] = True
    elif attack == "registry":
        kwargs["registry"] = "b" * 64
    elif attack == "not_final":
        changes["finality"] = "UNKNOWN_STATUS"
    elif attack == "partial":
        changes["home_goals"] = None
    elif attack == "unsupported":
        changes["home_goals"] = 37
    elif attack in {"bool", "string", "negative"}:
        changes["home_goals"] = {"bool": True, "string": "2", "negative": -1}[attack]
    elif attack == "before_lag":
        at -= timedelta(microseconds=1)
    elif attack == "freeze_day":
        changes["source_match_date"] = view.frozen_at.date()
    elif attack == "future_played":
        changes["source_match_date"] = AT.date() + timedelta(days=1)
    elif attack == "orientation":
        row = view.forecasts[-1].fixture
        changes["fixture"] = row.model_copy(
            update={"home_team_id": row.away_team_id, "away_team_id": row.home_team_id}
        )
    with pytest.raises((ValueError, TypeError)):
        snapshot = owned_snapshot(view, changes=changes, **kwargs)
        c.admit_canonical_labels(object() if attack == "non_view" else view, snapshot, as_of=at)


@pytest.mark.parametrize("attack", ["hash", "state", "empty_closure"])
def test_writer_reauthenticates_before_creating_artifact(tmp_path, attack):
    proposal = c.propose_canonical_binding()
    values = {name: getattr(proposal, name) for name in type(proposal).model_fields}
    if attack == "hash":
        values["semantic_sha256"] = "0" * 64
    elif attack == "state":
        values["state"] = "ACCEPTED"
    else:
        values["components"] = ()
    proposal = c.CanonicalCodeBinding.model_construct(**values)
    output = tmp_path / "denied.json"
    with pytest.raises(StrengthEvidenceError, match="WRITE_FAILED"):
        c.write_canonical_artifact(output, proposal)
    assert not output.exists()


def test_proposal_cli_writes_immutable_pending_artifact(tmp_path):
    path = tmp_path / "proposal.json"
    result = CliRunner().invoke(recovery_app, ["p01-canonical-proposal", "--output", str(path)])
    assert result.exit_code == 0 and json.loads(result.stdout)["scoring_authorized"] is False
    assert (
        c.CanonicalCodeBinding.model_validate_json(path.read_bytes()).state == "PROPOSED_UNACCEPTED"
    )
    assert (
        CliRunner()
        .invoke(recovery_app, ["p01-canonical-proposal", "--output", str(path)])
        .exit_code
        == 2
    )


def test_bad_original_is_refused_without_body_in_error_graph(tmp_path):
    path = tmp_path / "wrong.json"
    path.write_bytes(b"owned-private-wrong-body")
    with pytest.raises(StrengthEvidenceError) as caught:
        c.authenticate_original_p01(path)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_authority_hashes_and_empty_component_closure_are_strict():
    with pytest.raises(ValidationError):
        c.CanonicalAcceptances(accepted_code_bindings=("not-a-digest",))
    with pytest.raises(ValidationError):
        seal(c.CanonicalCodeBinding, components=(), governance_history=())
