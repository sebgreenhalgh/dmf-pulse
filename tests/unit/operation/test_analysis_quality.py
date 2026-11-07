"""Offline quality diagnostics preserve missing evidence and the champion outputs."""

import json
import socket
import sqlite3
from contextlib import closing
from decimal import Decimal
from functools import cache

import pytest
from typer.testing import CliRunner

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.cli.app import app
from dmf_pulse.dashboard.synthetic import DEMO_TIME
from dmf_pulse.operation.analysis_quality import diagnose_forecast
from dmf_pulse.operation.analysis_store import AnalysisStore
from tests.unit.operation.analysis_test_support import load_owned_snapshot


@pytest.fixture(scope="module")
def snapshot():
    return _snapshot()


@cache
def _snapshot():
    return load_owned_snapshot()


def change_row(snapshot, **updates):
    first, *rest = snapshot.view.players
    return snapshot.model_copy(
        update={
            "view": snapshot.view.model_copy(
                update={"players": (first.model_copy(update=updates), *rest)}
            )
        }
    )


def historical(snapshot):
    return snapshot.model_copy(update={"presentation": None})


def test_deterministic_pure_report_and_explicit_unavailable_attribution(snapshot):
    before = snapshot.model_dump_json()
    report = diagnose_forecast(snapshot)
    assert report == diagnose_forecast(snapshot)
    assert snapshot.model_dump_json() == before
    assert report.snapshot_sha256 == snapshot.semantic_sha256
    assert report.provenance_class == snapshot.provenance_class
    assert report.permission_origin == snapshot.permission_origin
    assert report.rights == snapshot.rights
    assert report.player_count == len(snapshot.view.players)
    assert report.validation == "UNVALIDATED"
    assert report.predictive_performance is None
    assert report.monte_carlo_policy is None
    assert report.team.autosub_expected_points is None
    assert report.team.vice_contingency_expected_points is None
    assert report.team.captain_only_counterfactual is None
    assert report.team.status == "MARGINAL_ACCOUNTING_ONLY"
    assert report.team.retained_before_hit == (
        report.team.xi_plus_standalone_captain + report.team.unattributed_difference
    )
    assert (
        report.team.retained_after_hit == report.team.retained_before_hit - report.team.hit_points
    )
    assert not report.issues


@pytest.mark.parametrize(
    ("points", "minutes", "expected"),
    [
        (None, None, "MISSING_POINTS"),
        (0.0, None, "ZERO_POINTS_MINUTES_UNKNOWN"),
        (0.0, "0.000000", "ZERO_POINTS_ZERO_MINUTES_CAUSE_UNAVAILABLE"),
        (0.0, "10.000000", "ZERO_POINTS_POSITIVE_MINUTES"),
        (1.0, "10.000000", "NONZERO_POINTS"),
    ],
)
def test_zero_is_never_missing_or_a_fabricated_unavailability_reason(
    snapshot, points, minutes, expected
):
    report = diagnose_forecast(
        change_row(historical(snapshot), expected_points=points, expected_minutes=minutes)
    )
    assert report.players[0].zero_status == expected
    assert report.players[0].p_zero_minutes is None
    assert report.players[0].minutes_confidence_reasons is None
    assert report.missing_points_count == int(points is None) + sum(
        row.expected_points is None for row in snapshot.view.players[1:]
    )


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "garbage", "-1", "1.000001"])
def test_bad_retained_probability_is_reported_without_silently_zero_filling(snapshot, bad):
    report = diagnose_forecast(change_row(historical(snapshot), p_start=bad))
    assert "P_START_INVALID" in report.players[0].issues


def test_missing_quantiles_standard_error_and_minutes_are_null(snapshot):
    altered = historical(snapshot)
    rows = tuple(
        row.model_copy(
            update={"monte_carlo_mean_se": None, "points_p10": None, "expected_minutes": None}
        )
        for row in altered.view.players
    )
    report = diagnose_forecast(
        altered.model_copy(update={"view": altered.view.model_copy(update={"players": rows})})
    )
    assert report.maximum_retained_mean_se is None
    assert report.p10_missing_count == len(rows)
    assert report.p10_zero_count == 0


def test_identity_regression_detects_two_official_players_sharing_one_canonical_id(snapshot):
    altered = historical(snapshot)
    first, second, *rest = altered.view.players
    second = second.model_copy(
        update={
            "catalogue": second.catalogue.model_copy(
                update={"player_id": first.catalogue.player_id}
            )
        }
    )
    altered = altered.model_copy(
        update={"view": altered.view.model_copy(update={"players": (first, second, *rest)})}
    )
    assert "DUPLICATE_CANONICAL_PLAYER_ID" in diagnose_forecast(altered).issues


def test_marginals_missing_from_selected_xi_do_not_produce_an_accounting_zero(snapshot):
    chosen = snapshot.view.team.decision.tactics.captain
    rows = tuple(
        row.model_copy(update={"expected_points": None})
        if row.catalogue.player_id == chosen
        else row
        for row in snapshot.view.players
    )
    altered = historical(snapshot).model_copy(
        update={"view": snapshot.view.model_copy(update={"players": rows})}
    )
    report = diagnose_forecast(altered)
    assert report.team.status == "INCOMPLETE_MARGINALS"
    assert report.team.starting_xi_expected_points is None
    assert report.team.unattributed_difference is None
    assert isinstance(report.team.retained_before_hit, Decimal)


def test_nonmonotone_quantiles_and_minutes_mismatch_are_reported(snapshot):
    report = diagnose_forecast(
        change_row(snapshot, points_p10=20, points_p90=0, expected_minutes="-1")
    )
    assert "EXPECTED_MINUTES_INVALID" in report.players[0].issues
    assert "QUANTILES_NOT_MONOTONE" in report.players[0].issues
    assert "RETAINED_MINUTES_MISMATCH" in report.players[0].issues


def test_signed_probability_masses_cannot_hide_behind_normalized_mean(snapshot):
    presentation = snapshot.presentation
    first, *other = presentation.gameweeks
    key, summary = next(iter(first.summaries.items()))
    pmf = dict(summary.pmf)
    for score, change in ((100, -0.1), (101, 0.2), (102, -0.1)):
        pmf[score] = pmf.get(score, 0) + change
    summaries = first.summaries | {key: summary.model_copy(update={"pmf": pmf})}
    altered = snapshot.model_copy(
        update={
            "presentation": presentation.model_copy(
                update={"gameweeks": (first.model_copy(update={"summaries": summaries}), *other)}
            )
        }
    )
    assert "POINTS_PMF_MASS_INVALID" in diagnose_forecast(altered).issues


def test_nonzero_points_zero_minutes_and_negative_numerical_uncertainty(snapshot):
    report = diagnose_forecast(
        change_row(
            historical(snapshot),
            expected_points=1.0,
            expected_minutes="0.000000",
            monte_carlo_mean_se=-1.0,
            points_standard_deviation=-1.0,
        )
    )
    assert set(report.players[0].issues) >= {
        "NONZERO_POINTS_WITH_ZERO_EXPECTED_MINUTES",
        "MEAN_SE_NEGATIVE",
        "STANDARD_DEVIATION_NEGATIVE",
    }


@pytest.mark.parametrize("kind", ["mass", "mean", "gameweek", "fixture", "catalogue_count"])
def test_corrupt_distribution_and_duplicate_identity_diagnostics(snapshot, kind):
    presentation = snapshot.presentation
    first, *other = presentation.gameweeks
    key, summary = next(iter(first.summaries.items()))
    if kind in {"mass", "mean"}:
        pmf = {100: 0.5 if kind == "mass" else 1.0}
        first = first.model_copy(
            update={"summaries": first.summaries | {key: summary.model_copy(update={"pmf": pmf})}}
        )
        presentation = presentation.model_copy(update={"gameweeks": (first, *other)})
        expected = "POINTS_PMF_NOT_NORMALIZED" if kind == "mass" else "POINTS_PMF_MEAN_MISMATCH"
    elif kind == "gameweek":
        presentation = presentation.model_copy(
            update={"gameweeks": (*presentation.gameweeks, first)}
        )
        expected = "DUPLICATE_GAMEWEEK_IDENTITY"
    elif kind == "fixture":
        presentation = presentation.model_copy(
            update={"fixtures": (*presentation.fixtures, presentation.fixtures[0])}
        )
        expected = "DUPLICATE_FIXTURE_IDENTITY"
    else:
        altered = snapshot.model_copy(
            update={
                "view": snapshot.view.model_copy(
                    update={"catalogue_count": snapshot.view.catalogue_count + 1}
                )
            }
        )
        assert "CATALOGUE_COUNT_MISMATCH" in diagnose_forecast(altered).issues
        return
    assert (
        expected
        in diagnose_forecast(snapshot.model_copy(update={"presentation": presentation})).issues
    )


@pytest.mark.parametrize("kind", ["zero", "position"])
def test_exact_zero_minute_pmf_and_resealed_fixture_position_are_distinguished(snapshot, kind):
    presentation = snapshot.presentation
    first, *other = presentation.fixtures
    key, original = next(iter(first.minutes.items()))
    body = original.model_dump(mode="json")
    if kind == "zero":
        body.update(
            p_start="0.000000000000",
            p_bench="0.000000000000",
            p_out_of_squad="1.000000000000",
            p_appearance="0.000000000000",
            p_zero_minutes="1.000000000000",
            p_60_plus="0.000000000000",
            expected_minutes="0.000000",
            minute_pmf=["1.000000000000"] + ["0.000000000000"] * 90,
        )
    else:
        body["position"] = "FWD" if original.position != "FWD" else "GK"
    body["projection_sha256"] = canonical_sha256(
        {k: v for k, v in body.items() if k != "projection_sha256"}
    )
    changed = type(original).model_validate_json(json.dumps(body))
    presentation = presentation.model_copy(
        update={
            "fixtures": (
                first.model_copy(update={"minutes": first.minutes | {key: changed}}),
                *other,
            )
        }
    )
    view = snapshot.view
    if kind == "zero":
        rows = tuple(
            row.model_copy(update={"expected_points": 0.0, "expected_minutes": "0.000000"})
            if row.catalogue.player_id == key
            else row
            for row in view.players
        )
        view = view.model_copy(update={"players": rows})
    report = diagnose_forecast(
        snapshot.model_copy(update={"presentation": presentation, "view": view})
    )
    player = next(row for row in report.players if row.player_id == key)
    if kind == "zero":
        assert player.zero_status == "ZERO_POINTS_ZERO_MINUTES_PMF_CONFIRMED"
        assert player.p_zero_minutes == "1.000000000000"
    else:
        assert "FIXTURE_PLAYER_IDENTITY_MISMATCH" in player.issues


def test_cli_reads_v1_without_migration_network_credentials_or_forecast_execution(
    snapshot, tmp_path, monkeypatch
):
    from dmf_pulse.credentials.service import CredentialService

    store = AnalysisStore(tmp_path / "history" / "quality.sqlite")
    store.initialize()
    digest = store.stage(snapshot)
    store.confirm(snapshot.run_id, digest, "4" * 64, at=DEMO_TIME)
    with closing(sqlite3.connect(store.path)) as connection, connection:
        for name in (
            "player_component_metrics_v2",
            "player_fixture_metrics_v2",
            "player_gameweek_metrics_v2",
        ):
            connection.execute(f"DROP VIEW {name}")
        connection.execute("PRAGMA user_version=1")
    before = store.path.read_bytes()

    def denied(*args, **kwargs):
        pytest.fail("offline quality called a prohibited capability")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(CredentialService, "resolve", denied)
    monkeypatch.setattr(CredentialService, "status", denied)
    monkeypatch.setattr(AnalysisStore, "initialize", denied)
    result = CliRunner().invoke(
        app, ["analysis", "quality", "--database", str(store.path), "--run-id", snapshot.run_id]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["snapshot_sha256"] == digest
    assert store.path.read_bytes() == before
    result = CliRunner().invoke(
        app, ["analysis", "quality", "--database", str(store.path), "--run-id", "absent"]
    )
    assert result.exit_code == 2
    assert result.output.strip() == "ANALYSIS_READ_ONLY_QUALITY_FAILED"


def test_missing_database_is_not_created_and_error_is_closed(tmp_path):
    path = tmp_path / "absent.sqlite"
    result = CliRunner().invoke(app, ["analysis", "quality", "--database", str(path)])
    assert result.exit_code == 2
    assert result.output.strip() == "ANALYSIS_READ_ONLY_QUALITY_FAILED"
    assert not path.exists()
