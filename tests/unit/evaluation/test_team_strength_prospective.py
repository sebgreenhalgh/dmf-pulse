"""Synthetic public-only forecast freeze, lineage, leakage and scoring controls."""

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from functools import lru_cache

import pytest

from dmf_pulse.evaluation.team_strength_prospective import (
    PrivateProspectiveStorageDenied,
    PromotionEvidenceStatus,
    PublicForecastBuildRequestV1,
    PublicForecastDistribution,
    PublicTeamStrengthForecastV1,
    freeze_public_team_forecasts,
    prospective_calibration,
    require_public_prospective_storage,
    score_public_team_forecasts,
)
from dmf_pulse.evaluation.team_strength_prospective_store import (
    load_public_forecast,
    persist_public_forecast,
)
from dmf_pulse.football_events.team_strength_parameter_draws import (
    draw_policy,
    joint_parameter_draws,
)
from dmf_pulse.ingestion.openfootball.service import CurrentScorePriorBuildRequest
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SourceLineage,
    SourceResource,
    parse_snapshot,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import load_historical_team_identity
from tests.unit.ingestion.openfootball.conftest import FakeTransport, synthetic_snapshot
from tests.unit.ingestion.openfootball.test_service import _service
from tests.unit.private_v1.team_strength_shadow_support import STAMP, synthetic_strength


@lru_cache(maxsize=2)
def frozen(mode="RECONSTRUCTED"):
    dataset, artifact = synthetic_strength(mode=mode)
    origin = STAMP + timedelta(seconds=2)
    draws = joint_parameter_draws(artifact, policy=draw_policy(seed=23, draw_count=11))
    schedule = dataset.sources[-1]
    config, bodies = synthetic_snapshot()
    baseline = _service(config, FakeTransport(bodies)).build(
        CurrentScorePriorBuildRequest(
            information_cutoff=STAMP, rights_profile_id="openfootball_football_json_score_prior_v1"
        )
    )
    return freeze_public_team_forecasts(
        artifact=artifact,
        draws=draws,
        fixture_registry=dataset.fixture_registry,
        public_schedule=schedule,
        training_dataset=dataset,
        forecast_origin=origin,
        fixture_ids=(str(schedule.matches[0].fixture.fixture_id),),
        league_baseline=baseline,
        clock=lambda: origin,
    )


def outcome(value, *, goals=(2, 1), at=datetime(2026, 10, 6, tzinfo=UTC), played="2026-10-04"):
    fixture = value.forecasts[0].fixture
    identity = load_historical_team_identity()
    names = {
        row.canonical_team_id: row.source_team_name
        for row in identity.records
        if fixture.season in row.season_scope
    }
    body = json.dumps(
        {
            "name": f"English Premier League {fixture.season}",
            "matches": [
                {
                    "team1": names[fixture.home_team_id],
                    "team2": names[fixture.away_team_id],
                    "date": played,
                    "round": "Matchday 1",
                    "score": {"ft": list(goals)},
                }
            ],
        }
    ).encode()
    resource = SourceResource(
        commit="d" * 40,
        season=fixture.season,
        path=fixture.season.replace("/", "-") + "/en.1.json",
        git_blob_sha1=hashlib.sha1(
            f"blob {len(body)}\0".encode() + body, usedforsecurity=False
        ).hexdigest(),
        content_sha256=hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
    )
    lineage = seal(
        SourceLineage,
        resource=resource,
        retrieval_started_at=at,
        received_at=at,
        validated_at=at,
        usable_at=at,
        acquisition="LOCAL_IMMUTABLE_IMPORT",
    )
    return parse_snapshot(
        body,
        lineage=lineage,
        fixtures=value.fixture_registry,
        expected_fixture_registry_sha256=value.fixture_registry.semantic_sha256,
    )


def test_public_forecast_frozen_serialized_and_three_products_comparable(tmp_path):
    value = frozen()
    assert value.dataset_mode == "RECONSTRUCTED"
    assert PublicTeamStrengthForecastV1.model_validate_json(value.model_dump_json()) == value
    first = persist_public_forecast(value, artifact_root=tmp_path)
    assert persist_public_forecast(value, artifact_root=tmp_path) == first
    assert load_public_forecast(first, expected_forecast_sha256=value.semantic_sha256) == value
    before = first.read_bytes()
    scored = score_public_team_forecasts(
        value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    assert len(scored.scores) == 3
    assert {row[1] for row in scored.scores} == {
        "LEAGUE_BASELINE",
        "PLUG_IN_TEAM_STRENGTH_SHADOW",
        "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW",
    }
    assert (
        score_public_team_forecasts(
            value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
        )
        == scored
    )
    assert first.read_bytes() == before and scored.forecast_sha256 == value.semantic_sha256
    assert not scored.promotion.production_active and not scored.promotion.automatic_activation
    assert not list(tmp_path.rglob("*.partial"))


def test_later_corrected_outcome_changes_score_without_changing_forecast():
    value = frozen()
    first = score_public_team_forecasts(
        value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    second = score_public_team_forecasts(
        value, outcomes=outcome(value, goals=(0, 0)), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    assert first.semantic_sha256 != second.semantic_sha256
    assert first.forecast_sha256 == second.forecast_sha256 == value.semantic_sha256


def test_live_label_requires_accepted_time_safe_live_model_and_dataset():
    value = frozen("LIVE_OBSERVED")
    assert value.dataset_mode == "LIVE_OBSERVED"
    values = {
        name: getattr(frozen(), name)
        for name in type(value).model_fields
        if name != "semantic_sha256"
    }
    values["dataset_mode"] = "LIVE_OBSERVED"
    with pytest.raises(ValueError, match="masquerade"):
        seal(PublicTeamStrengthForecastV1, **values)


@pytest.mark.parametrize(
    "private_field",
    ["manager_state", "player_projections", "candidate_screen", "odds_forecast", "fpl_payload"],
)
def test_private_fields_are_not_in_forecast_schema(private_field):
    value = frozen()
    payload = json.loads(value.model_dump_json())
    payload[private_field] = {"private": "sentinel"}
    with pytest.raises(ValueError):
        PublicTeamStrengthForecastV1.model_validate_json(json.dumps(payload))


def test_private_storage_fails_before_filesystem_access(tmp_path):
    before = tuple(tmp_path.iterdir())
    with pytest.raises(PrivateProspectiveStorageDenied) as caught:
        require_public_prospective_storage("PRIVATE_FPL_DERIVED")
    assert caught.value.code == "PRIVATE_PROSPECTIVE_STORAGE_NOT_AUTHORIZED"
    with pytest.raises(PrivateProspectiveStorageDenied):
        persist_public_forecast(object(), artifact_root=tmp_path)
    assert tuple(tmp_path.iterdir()) == before


@pytest.mark.parametrize("collision", [False, True])
def test_atomic_forecast_publication_race_is_immutable(tmp_path, monkeypatch, collision):
    from dmf_pulse.evaluation import team_strength_prospective_store as store

    value = frozen()

    def race(temporary, destination):
        destination.write_bytes(b"collision" if collision else temporary.read_bytes())
        raise FileExistsError

    monkeypatch.setattr(store.os, "link", race)
    if collision:
        with pytest.raises(ValueError, match="publication collision"):
            persist_public_forecast(value, artifact_root=tmp_path)
        with pytest.raises(ValueError, match="identity collision"):
            persist_public_forecast(value, artifact_root=tmp_path)
    else:
        path = persist_public_forecast(value, artifact_root=tmp_path)
        assert load_public_forecast(path, expected_forecast_sha256=value.semantic_sha256) == value
        with pytest.raises(ValueError, match="expected immutable"):
            load_public_forecast(path, expected_forecast_sha256="0" * 64)
    assert not list(tmp_path.rglob(".public-forecast-*"))


@pytest.mark.parametrize("case", ["weight", "multiple_plugin", "duplicate_mixture"])
def test_invalid_forecast_component_contract_fails(case):
    value = frozen().forecasts[0].distributions[1]
    fields = value.model_dump(mode="python")
    half = value.rates[0].model_copy(update={"draw_weight": Decimal("0.5")})
    if case == "weight":
        fields["rates"] = (half,)
    elif case == "multiple_plugin":
        fields["rates"] = (half, half.model_copy(update={"parameter_draw_id": "0" * 64}))
    else:
        fields |= {"product": "PARAMETER_MIXTURE_TEAM_STRENGTH_SHADOW", "rates": (half, half)}
    with pytest.raises(ValueError):
        PublicForecastDistribution.model_validate(fields)


@pytest.mark.parametrize(
    "at,played,cutoff",
    [
        (STAMP, "2026-10-04", datetime(2026, 10, 6, tzinfo=UTC)),
        (datetime(2026, 10, 2, tzinfo=UTC), "2026-10-04", datetime(2026, 10, 6, tzinfo=UTC)),
        (datetime(2026, 10, 4, tzinfo=UTC), "2026-10-04", datetime(2026, 10, 5, tzinfo=UTC)),
        (datetime(2026, 10, 6, tzinfo=UTC), "2026-09-30", datetime(2026, 10, 6, tzinfo=UTC)),
    ],
)
def test_pre_freeze_pre_played_and_ineligible_outcomes_rejected(at, played, cutoff):
    value = frozen()
    with pytest.raises(ValueError):
        score_public_team_forecasts(
            value, outcomes=outcome(value, at=at, played=played), as_of=cutoff
        )


def test_impossible_score_support_and_naive_times_rejected():
    value = frozen()
    with pytest.raises(ValueError, match="support"):
        score_public_team_forecasts(
            value, outcomes=outcome(value, goals=(37, 0)), as_of=datetime(2026, 10, 6, tzinfo=UTC)
        )
    with pytest.raises(ValueError):
        score_public_team_forecasts(value, outcomes=outcome(value), as_of=datetime(2026, 10, 6))


def test_proper_scores_against_independent_single_component_oracle():
    value = frozen()
    scored = score_public_team_forecasts(
        value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    plugin = value.forecasts[0].distributions[1]
    metrics = dict(scored.scores[1][2])
    home, away = float(plugin.rates[0].lambda_home), float(plugin.rates[0].lambda_away)
    probability = math.exp(-home - away) * home**2 / math.factorial(2) * away
    assert abs(metrics["exact_score_log_loss"] + Decimal(str(math.log(probability)))) < Decimal(
        "1e-12"
    )
    assert metrics["home_clean_sheet_brier"] > 0


def test_calibration_retains_population_and_rejects_mixed_modes():
    reports = tuple(
        score_public_team_forecasts(
            value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
        )
        for value in (frozen(), frozen("LIVE_OBSERVED"))
    )
    diagnostics = prospective_calibration((reports[0],))
    assert len(diagnostics) == 33
    assert all(row.dataset_mode == "RECONSTRUCTED" for row in diagnostics)
    assert all(row.forecast_sha256s == (reports[0].forecast_sha256,) for row in diagnostics)
    assert all(row.score_report_sha256s == (reports[0].semantic_sha256,) for row in diagnostics)
    with pytest.raises(ValueError, match="dataset modes"):
        prospective_calibration(reports)
    with pytest.raises(ValueError, match="distinct"):
        prospective_calibration((reports[0], reports[0]))


def test_frozen_forecast_rejects_rehashed_late_freeze_and_invented_rates():
    value = frozen()
    fields = {
        name: getattr(value, name) for name in type(value).model_fields if name != "semantic_sha256"
    }
    with pytest.raises(ValueError, match="scheduled match day"):
        seal(type(value), **(fields | {"frozen_at": datetime(2026, 10, 4, tzinfo=UTC)}))
    product = value.forecasts[0].distributions[1]
    changed = product.model_copy(
        update={
            "rates": (product.rates[0].model_copy(update={"lambda_home": Decimal("1.000000")}),)
        }
    )
    fixture = value.forecasts[0].model_copy(
        update={
            "distributions": (
                value.forecasts[0].distributions[0],
                changed,
                value.forecasts[0].distributions[2],
            )
        }
    )
    with pytest.raises(ValueError, match="frozen model"):
        seal(type(value), **(fields | {"forecasts": (fixture,)}))


def test_forecast_rejects_known_training_target_and_different_source_vintage():
    value = frozen()
    fields = {
        name: getattr(value, name) for name in type(value).model_fields if name != "semantic_sha256"
    }
    training_fixture = value.training_dataset.matches[0].observation.fixture
    trained = value.forecasts[0].model_copy(update={"fixture": training_fixture})
    with pytest.raises(ValueError, match="already used to fit"):
        seal(type(value), **(fields | {"forecasts": (trained,)}))
    with pytest.raises(ValueError, match="bound fitted source vintage"):
        seal(type(value), **(fields | {"public_schedule": outcome(value)}))
    with pytest.raises(ValueError, match="post-origin"):
        seal(type(value), **(fields | {"forecast_origin": STAMP}))


def test_promotion_gate_cannot_be_weakened():
    with pytest.raises(ValueError, match="cannot be weakened"):
        PromotionEvidenceStatus(required_evidence=("ONE_GAMEWEEK",))


@pytest.mark.parametrize(
    "metric,changed",
    [
        ("exact_score_log_loss", Decimal(-1)),
        ("goal_rps", Decimal(37)),
        ("home_clean_sheet_brier", Decimal(-1)),
        ("home_clean_sheet_brier", Decimal("0.2")),
        ("home_clean_sheet_calibration_residual", Decimal("0.2")),
    ],
)
def test_rehashed_inconsistent_scores_rejected(metric, changed):
    value = frozen()
    report = score_public_team_forecasts(
        value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    fixture, product, pairs = report.scores[0]
    metrics = dict(pairs) | {metric: changed}
    fields = {
        name: getattr(report, name)
        for name in type(report).model_fields
        if name != "semantic_sha256"
    }
    fields["scores"] = ((fixture, product, tuple(sorted(metrics.items()))), *report.scores[1:])
    with pytest.raises(ValueError):
        seal(type(report), **fields)


def test_rehashed_inconsistent_multiclass_outcomes_rejected():
    value = frozen()
    report = score_public_team_forecasts(
        value, outcomes=outcome(value), as_of=datetime(2026, 10, 6, tzinfo=UTC)
    )
    fixture, product, pairs = report.scores[0]
    metrics = dict(pairs)
    for event in ("home_win", "draw", "away_win"):
        probability = metrics[event + "_probability"]
        metrics[event + "_outcome"] = Decimal(0)
        with localcontext() as context:
            context.prec = 60
            metrics[event + "_brier"] = probability**2
            metrics[event + "_calibration_residual"] = probability
    fields = {
        name: getattr(report, name)
        for name in type(report).model_fields
        if name != "semantic_sha256"
    }
    fields["scores"] = ((fixture, product, tuple(sorted(metrics.items()))), *report.scores[1:])
    with pytest.raises(ValueError, match="1X2"):
        seal(type(report), **fields)


def test_public_cli_freezes_scores_and_fails_safely(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from dmf_pulse.cli import team_strength as commands
    from dmf_pulse.cli.app import app
    from dmf_pulse.evaluation.team_strength_prospective import freeze_public_forecast_request

    value = frozen()
    request = PublicForecastBuildRequestV1(
        artifact=value.artifact,
        expected_artifact_sha256=value.artifact.semantic_sha256,
        training_dataset=value.training_dataset,
        fixture_registry=value.fixture_registry,
        public_schedule=value.public_schedule,
        draw_policy=value.draw_set.policy,
        forecast_origin=value.forecast_origin,
        fixture_ids=(value.forecasts[0].fixture.fixture_id,),
        league_baseline=value.league_baseline,
    )
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        commands,
        "freeze_public_forecast_request",
        lambda request: freeze_public_forecast_request(request, clock=lambda: value.frozen_at),
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "events",
            "team-strength",
            "prospective-freeze",
            "--request",
            str(path),
            "--retained-artifact-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["forecast_sha256"] == value.semantic_sha256
    stored = tmp_path / "public-team-strength-prospective" / (value.semantic_sha256 + ".json")
    played = tmp_path / "outcome.json"
    played.write_text(outcome(value).model_dump_json(), encoding="utf-8")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 6, tzinfo=UTC)

    monkeypatch.setattr(commands, "datetime", Clock)
    result = runner.invoke(
        app,
        [
            "events",
            "team-strength",
            "prospective-score",
            "--forecast",
            str(stored),
            "--forecast-sha256",
            value.semantic_sha256,
            "--outcomes",
            str(played),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert len(json.loads(result.stdout)["scores"]) == 3
    path.write_text('{"manager_state":"sentinel-private"}', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "events",
            "team-strength",
            "prospective-freeze",
            "--request",
            str(path),
            "--retained-artifact-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 2 and "sentinel-private" not in result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "SHADOW_EVIDENCE_INVALID"
