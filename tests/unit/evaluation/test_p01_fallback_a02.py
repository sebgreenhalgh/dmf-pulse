"""A02 T01-T19: synthetic only; provider operations cannot run during tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.cli.app import app
from dmf_pulse.evaluation.p01_fallback import (
    P01FallbackReconciliationV1,
    P01FallbackScorecardV1,
    _score_admitted,
    fallback_scorecard,
    reconcile_openfootball,
    score_p01_fallback,
)
from dmf_pulse.evaluation.p01_fallback_context import (
    CONTEXT_SHA,
    P01FallbackContext,
    authenticate_p01,
    load_context,
    require_forecast_binding,
    require_openligadb_rights,
)
from dmf_pulse.evaluation.p01_fallback_store import load_fallback, persist_fallback
from dmf_pulse.evaluation.team_strength_prospective import (
    PublicProspectiveScoreV1,
    PublicTeamStrengthForecastV1,
    freeze_public_team_forecasts,
    score_public_fixture_labels,
    score_public_team_forecasts,
)
from dmf_pulse.ingestion import p01_fallback_acquisition as acquisition
from dmf_pulse.ingestion.openfootball.team_strength_data import (
    SourceLineage,
    SourceResource,
    parse_snapshot,
    seal,
)
from dmf_pulse.ingestion.openfootball.team_strength_governance import (
    eligibility_not_before,
    load_historical_team_identity,
)
from dmf_pulse.ingestion.p01_fallback import (
    PublicP01FallbackOutcomesV1,
    admit_final_facts,
    project_final_facts,
    regulation_type,
    require_d_plus_2,
    source_receipt,
)
from tests.unit.evaluation.test_team_strength_prospective import frozen, outcome

AT = datetime(2026, 10, 6, tzinfo=UTC)
GLOBAL = json.dumps([{"id": 1, "kind": "After90Minutes"}, {"id": 2, "kind": "HalfTime"}]).encode()
LEAGUE = json.dumps([{"id": 7, "globalResultInfo": {"id": 1, "kind": "After90Minutes"}}]).encode()


@lru_cache(maxsize=1)
def ten_forecast():
    first = frozen()
    schedule = first.public_schedule
    return freeze_public_team_forecasts(
        artifact=first.artifact,
        draws=first.draw_set,
        training_dataset=first.training_dataset,
        fixture_registry=first.fixture_registry,
        public_schedule=schedule,
        forecast_origin=first.forecast_origin,
        fixture_ids=tuple(str(row.fixture.fixture_id) for row in schedule.matches[:10]),
        league_baseline=first.league_baseline,
        clock=lambda: first.frozen_at,
    )


@lru_cache(maxsize=1)
def synthetic_context():
    forecast = ten_forecast()
    names = {
        row.canonical_team_id: row.canonical_name
        for row in load_historical_team_identity().canonical_clubs
    }
    values = load_context().model_dump(mode="python", exclude={"semantic_sha256"})
    values.update(
        forecast_sha256=forecast.semantic_sha256,
        forecast_byte_sha256=hashlib.sha256(forecast.model_dump_json().encode()).hexdigest(),
        forecast_origin=forecast.forecast_origin,
        frozen_at=forecast.frozen_at,
        fixture_registry_sha256=forecast.fixture_registry.semantic_sha256,
        draw_policy_sha256=forecast.draw_set.draw_policy_sha256,
        amended_at=datetime(2026, 10, 3, tzinfo=UTC),
        fixtures=tuple(
            load_context()
            .fixtures[0]
            .__class__(
                fixture=row.fixture,
                scheduled_date=row.scheduled_date,
                home_aliases=(names[row.fixture.home_team_id],),
                away_aliases=(names[row.fixture.away_team_id],),
            )
            for row in forecast.forecasts
        ),
    )
    return seal(P01FallbackContext, **values)


def provider_rows():
    context = synthetic_context()
    clubs = sorted(
        {
            team
            for row in context.fixtures
            for team in (row.fixture.home_team_id, row.fixture.away_team_id)
        }
    )
    ids = {club: i + 100 for i, club in enumerate(clubs)}
    return [
        {
            "matchID": 1000 + i,
            "leagueId": 5996,
            "leagueShortcut": "pl",
            "leagueSeason": 2026,
            "leagueName": "Premier League",
            "group": {"groupOrderID": 6},
            "team1": {"teamId": ids[row.fixture.home_team_id], "teamName": row.home_aliases[0]},
            "team2": {"teamId": ids[row.fixture.away_team_id], "teamName": row.away_aliases[0]},
            "matchDateTimeUTC": "2026-10-04T14:00:00Z",
            "matchIsFinished": True,
            "matchResults": [
                {
                    "resultID": 2000 + i,
                    "resultTypeID": 7,
                    "resultTypeKind": "After90Minutes",
                    "pointsTeam1": i % 4,
                    "pointsTeam2": i % 3,
                    "resultName": "Endergebnis",
                },
                {
                    "resultID": 3000 + i,
                    "resultTypeID": 8,
                    "resultTypeKind": "HalfTime",
                    "pointsTeam1": 99,
                    "pointsTeam2": 99,
                },
            ],
            "goals": [{"playerName": "MUST_NOT_BE_RETAINED"}],
            "teamIconUrl": "MUST_NOT_BE_RETAINED",
        }
        for i, row in enumerate(context.fixtures)
    ]


def labels(*, rows=None, at=AT):
    context = synthetic_context()
    body = json.dumps(provider_rows() if rows is None else rows).encode()
    result_type = regulation_type(GLOBAL, LEAGUE)
    facts = project_final_facts(body, context=context, result_type=result_type)
    receipts = tuple(
        source_receipt(url, data, started=at, received=at)
        for url, data in zip(context.allowed_routes, (GLOBAL, LEAGUE, body), strict=True)
    )
    return admit_final_facts(
        facts,
        context=context,
        retrievals=receipts,
        result_type=result_type,
        validated_at=at,
        usable_at=at,
        attribution="OpenLigaDB; ODbL 1.0; internal synthetic test",
        independent_review_sha256="1" * 64,
        independently_reviewed_at=context.amended_at,
    )


def openfootball_for(labels_, *, changed=False, missing=False):
    rows = []
    for i, row in enumerate(labels_.outcomes):
        fact = row.source_fact
        rows.append(
            {
                "team1": fact.home_name,
                "team2": fact.away_name,
                "date": row.actual_played_date.isoformat(),
                "round": "Matchday 1",
                "score": {"ft": [row.home_goals + int(changed and i == 0), row.away_goals]},
            }
        )
    body = json.dumps(
        {"name": "English Premier League 2026/27", "matches": rows[:-1] if missing else rows}
    ).encode()
    resource = SourceResource(
        commit="d" * 40,
        season="2026/27",
        path="2026-27/en.1.json",
        git_blob_sha1=hashlib.sha1(
            f"blob {len(body)}\0".encode() + body, usedforsecurity=False
        ).hexdigest(),
        content_sha256=hashlib.sha256(body).hexdigest(),
        byte_length=len(body),
    )
    lineage = seal(
        SourceLineage,
        resource=resource,
        retrieval_started_at=AT,
        received_at=AT,
        validated_at=AT,
        usable_at=AT,
        acquisition="LOCAL_IMMUTABLE_IMPORT",
    )
    forecast = ten_forecast()
    return parse_snapshot(
        body,
        lineage=lineage,
        fixtures=forecast.fixture_registry,
        expected_fixture_registry_sha256=forecast.fixture_registry.semantic_sha256,
    )


def test_t01_t08_t16_pinned_governance_and_exact_original_metadata():
    context = load_context()
    assert context.semantic_sha256 == CONTEXT_SHA
    assert (
        context.forecast_sha256
        == "96a13e8265095672708586dd1fd2a7f9653857594ba5fa325e82c0b3385ab15a"
    )
    assert (
        context.forecast_byte_sha256
        == "e3b7db4ef8db933a6ff5ed940bbe0a250601ad1780361fbef4195282ed27f2ee"
    )
    assert (
        context.original_protocol_sha256
        == "93b9c2e8a0b0f6c00e1299cb410784daabf1eb04efa01baaab5f10d85d10e029"
    )
    assert (
        context.a01_amendment_sha256
        == "e621ebd745958e84f466f4708586df5d3f40bdca35659716650aba6585f79097"
    )
    assert (
        context.a02_amendment_sha256
        == "ae7bf0273623c47dd72f79d067117091c596f13245224acb2ccfadf47ff7ebd3"
    )
    assert len(context.fixtures) == 10 and context.frozen_at < context.amended_at
    assert (
        context.evaluation_epoch == "EVALUATION_EPOCH_003"
        and context.original_forecast_epoch == "EVALUATION_EPOCH_001"
    )
    assert not context.performance_metrics_inspected_before_amendment
    assert (
        "DESCRIPTIVE_PILOT_ONLY" in context.classifications
        and "NOT_CONFIRMATORY_EPOCH_001" in context.classifications
    )


def test_t01_forecast_byte_rejection_before_parsing(tmp_path):
    path = tmp_path / "forecast.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="BYTE_IDENTITY"):
        authenticate_p01(path)


def test_t09_rights_identity_exact_and_capabilities_before_transport(tmp_path, monkeypatch):
    profile = require_openligadb_rights()
    assert profile.rights_profile_id == "openligadb_public_final_score_labels_v1"
    assert profile.capabilities["automated_access"] == "ALLOW"
    assert (
        profile.capabilities["raw_storage"]
        == profile.capabilities["redistribution"]
        == profile.capabilities["public_display"]
        == "DENY"
    )
    from dmf_pulse.evaluation.p01_fallback_context import resource_bytes

    data = json.loads(resource_bytes("rights/openligadb_p01_fallback.json"))
    data["payload"]["capabilities"]["raw_storage"] = "ALLOW"
    data["semantic_sha256"] = canonical_sha256(data["payload"])
    path = tmp_path / "rights.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="RIGHTS_IDENTITY_MISMATCH"):
        require_openligadb_rights(path)
    calls = []
    monkeypatch.setattr(
        acquisition, "require_openligadb_rights", lambda: require_openligadb_rights(path)
    )

    class Transport:
        def get(self, url):
            calls.append(url)
            raise AssertionError("transport before rights")

    with pytest.raises(ValueError, match="RIGHTS_IDENTITY_MISMATCH"):
        acquisition.acquire_p01_once(
            forecast_path=tmp_path / "missing",
            review_path=tmp_path / "missing",
            expected_review_sha256="0" * 64,
            implementation_root=tmp_path,
            artifact_root=tmp_path,
            transport=Transport(),
        )
    assert calls == []


@pytest.mark.parametrize(
    "operation",
    [
        "missing",
        "extra",
        "duplicate",
        "reverse",
        "wrong_home",
        "duplicate_match_id",
        "duplicate_result_id",
        "club_id_collision",
    ],
)
def test_t02_t03_t07_exact_ten_unique_oriented_mapping(operation):
    rows = provider_rows()
    if operation == "missing":
        rows.pop()
    elif operation == "extra":
        rows.append(rows[0])
    elif operation == "duplicate":
        rows[1] = rows[0]
    elif operation == "reverse":
        rows[0]["team1"], rows[0]["team2"] = rows[0]["team2"], rows[0]["team1"]
    elif operation == "wrong_home":
        rows[0]["team1"]["teamName"] = "Unknown club"
    elif operation == "duplicate_match_id":
        rows[1]["matchID"] = rows[0]["matchID"]
    elif operation == "duplicate_result_id":
        rows[1]["matchResults"][0]["resultID"] = rows[0]["matchResults"][0]["resultID"]
    else:
        rows[1]["team2"]["teamId"] = rows[0]["team2"]["teamId"]
    with pytest.raises(ValueError):
        labels(rows=rows)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("leagueId", 5997),
        ("leagueId", True),
        ("leagueShortcut", "bl1"),
        ("leagueSeason", 2025),
        ("leagueName", "Other league"),
    ],
)
def test_t04_wrong_source_identity(field, bad):
    rows = provider_rows()
    rows[0][field] = bad
    with pytest.raises(ValueError):
        labels(rows=rows)


@pytest.mark.parametrize(
    "bad",
    [
        "unfinished",
        "halftime_only",
        "extra_time",
        "penalties",
        "ambiguous",
        "kind_mismatch",
        "type_mismatch",
        "abandoned",
        "award",
    ],
)
def test_t05_t07_unambiguous_finished_regulation_result(bad):
    rows = provider_rows()
    row = rows[0]
    final = row["matchResults"][0]
    if bad == "unfinished":
        row["matchIsFinished"] = False
    elif bad == "halftime_only":
        row["matchResults"].pop(0)
    elif bad in ("extra_time", "penalties"):
        final["resultTypeKind"] = bad
        final["resultTypeID"] = 99
    elif bad == "ambiguous":
        row["matchResults"].append(dict(final))
    elif bad == "kind_mismatch":
        final["resultTypeKind"] = "HalfTime"
    elif bad == "type_mismatch":
        final["resultTypeID"] = 8
    elif bad == "abandoned":
        final["resultDescription"] = "Abandoned"
    else:
        final["resultDescription"] = "Awarded"
    with pytest.raises(ValueError):
        labels(rows=rows)


def test_t05_metadata_must_agree_and_not_use_array_order():
    rows = provider_rows()
    for row in rows:
        row["matchResults"].reverse()
    assert labels(rows=rows).outcomes == labels().outcomes
    with pytest.raises(ValueError):
        regulation_type(GLOBAL, b'[{"id":7,"globalResultInfo":{"id":99,"kind":"After90Minutes"}}]')
    with pytest.raises(ValueError):
        regulation_type(b"[]", LEAGUE)


@pytest.mark.parametrize("score", [None, True, False, "2", 2.0, -1, 37, {}, []])
def test_t10_strict_goal_counts(score):
    rows = provider_rows()
    rows[0]["matchResults"][0]["pointsTeam1"] = score
    with pytest.raises(ValueError):
        labels(rows=rows)


def test_t06_t11_actual_date_d_plus_2_not_frozen_date():
    rows = provider_rows()
    rows[0]["matchDateTimeUTC"] = "2026-10-05T23:00:00Z"
    value = labels(rows=rows)
    assert value.outcomes[0].actual_played_date.isoformat() == "2026-10-05"
    assert value.outcomes[0].frozen_scheduled_date.isoformat() == "2026-10-04"
    boundary = eligibility_not_before(value.outcomes[0].actual_played_date)
    with pytest.raises(ValueError, match="P01_D_PLUS_2_NOT_COMPLETE"):
        require_d_plus_2(value, as_of=boundary - timedelta(microseconds=1))
    require_d_plus_2(value, as_of=boundary)
    for bad in (
        "2026-10-04",
        "2026-10-04T14:00:00",
        "2026-10-01T01:00:00Z",
        "2026-10-07T14:00:00Z",
    ):
        rows[0]["matchDateTimeUTC"] = bad
        with pytest.raises(ValueError):
            labels(rows=rows)
    with pytest.raises(ValueError):
        require_d_plus_2(value, as_of=datetime(2026, 10, 8))


@pytest.mark.parametrize(
    "field",
    [
        "source",
        "provenance",
        "context",
        "extract_sha256",
        "outcomes",
        "usable_at",
        "retrievals",
        "attribution",
    ],
)
def test_t12_semantic_tamper_rejected(field):
    value = labels()
    payload = json.loads(value.model_dump_json())
    if field == "outcomes":
        payload[field][0]["home_goals"] += 1
    elif field == "context":
        payload[field]["rights_profile_sha256"] = "0" * 64
    elif field == "retrievals":
        payload[field][2]["response_sha256"] = "0" * 64
    else:
        payload[field] = "tampered"
    with pytest.raises(ValueError):
        PublicP01FallbackOutcomesV1.model_validate_json(json.dumps(payload))


def test_t13_exclusive_content_addressed_storage_and_authentication(tmp_path):
    value = labels()
    path = persist_fallback(value, artifact_root=tmp_path)
    assert persist_fallback(value, artifact_root=tmp_path) == path
    assert load_fallback(path, expected_sha256=value.semantic_sha256) == value
    with pytest.raises(ValueError):
        load_fallback(path, expected_sha256="0" * 64)
    path.write_text("collision")
    with pytest.raises(ValueError, match="collision"):
        persist_fallback(value, artifact_root=tmp_path)
    with pytest.raises(ValueError):
        persist_fallback(ten_forecast(), artifact_root=tmp_path)
    assert not list(tmp_path.rglob(".p01-fallback-*"))


def test_t15_legacy_whole_envelope_equals_pre_refactor_oracle():
    reference = (
        Path(__file__).resolve().parents[2] / "fixtures/evaluation/a02_legacy_score_oracle.json"
    )
    golden = PublicProspectiveScoreV1.model_validate_json(reference.read_bytes())
    assert (
        golden.semantic_sha256 == "17e28605dde856abe21bfce41eb613130b394a5f153f0fb4df98bed333528ad9"
    )
    # Hold the accepted frozen INPUT fixed across platforms. Re-fitting the
    # synthetic corpus can change binary64 metadata hashes despite identical
    # stored six-place rates and scoring metrics; it is a different forecast.
    directory = reference.parent / "a02_legacy_forecast_input"
    manifest = json.loads((directory / "manifest.json").read_bytes())
    assert tuple(part["path"] for part in manifest["parts"]) == tuple(
        f"part-{index:03d}.json.part" for index in range(5)
    )
    assert manifest["captured_from_accepted_commit"] == "3815152e978dd55e1dc1f115055050d4ed6b1735"
    assert (
        manifest["input_byte_sha256"]
        == "1c2c0df07078456822c6cf40cb52fd6e97e551c0cdd6dd030851f72e0c5ffb0d"
    )
    chunks = []
    for part in manifest["parts"]:
        data = (directory / part["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == part["byte_sha256"]
        chunks.append(data)
    raw = b"".join(chunks)
    assert hashlib.sha256(raw).hexdigest() == manifest["input_byte_sha256"]
    value = PublicTeamStrengthForecastV1.model_validate_json(raw)
    assert value.semantic_sha256 == golden.forecast_sha256
    actual = score_public_team_forecasts(value, outcomes=outcome(value), as_of=AT)
    assert actual == golden


@lru_cache(maxsize=1)
def scored():
    return _score_admitted(ten_forecast(), outcomes=labels(), as_of=AT)


def test_t01_t14_t15_all_metrics_equal_through_both_typed_admissions():
    forecast = ten_forecast()
    before = forecast.model_dump_json()
    value = labels()
    original = score_public_team_forecasts(forecast, outcomes=openfootball_for(value), as_of=AT)
    fallback = scored()
    assert fallback.metrics.scores == original.scores
    assert len(original.scores) == 30
    assert all(len(pairs) == 49 for _, _, pairs in original.scores)
    assert before == forecast.model_dump_json()
    report = fallback_scorecard(fallback, outcomes=value)
    assert report.provenance == fallback.provenance == "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    assert report.score.context == value.context
    assert len(report.product_means) == 3 and len(report.loss_deltas) == 3
    assert all(len(product.event_brier_means) == 11 for product in report.product_means)
    assert "MUST_NOT_BE_RETAINED" not in value.model_dump_json()
    assert "OPENFOOTBALL_LIVE_OBSERVED" not in report.model_dump_json()
    payload = json.loads(report.model_dump_json())
    payload["product_means"][0]["metrics"][0][1] = "999"
    with pytest.raises(ValueError):
        P01FallbackScorecardV1.model_validate_json(json.dumps(payload))


def test_t16_t17_operational_gate_rejects_other_forecasts_and_contexts():
    with pytest.raises(ValueError):
        require_forecast_binding(frozen(), context=load_context())
    with pytest.raises(ValueError):
        score_p01_fallback(ten_forecast(), outcomes=labels(), as_of=AT)
    assert not scored().promotion.production_active
    assert not scored().promotion.automatic_activation
    for field, bad in (
        ("source", "Other"),
        ("production_active", True),
        ("promotion_permitted", True),
        ("performance_metrics_inspected_before_amendment", True),
    ):
        values = {key: value for key, value in synthetic_context() if key != "semantic_sha256"}
        values[field] = bad
        with pytest.raises(ValueError):
            seal(P01FallbackContext, **values)


def test_t18_future_reconciliation_full_disagreement_pending_append_only(tmp_path):
    value = labels()
    path = persist_fallback(value, artifact_root=tmp_path)
    before = path.read_bytes()
    full = reconcile_openfootball(value, snapshot=openfootball_for(value), audited_at=AT)
    disagreement = reconcile_openfootball(
        value, snapshot=openfootball_for(value, changed=True), audited_at=AT
    )
    assert full.status == "FULL_RECONCILIATION" and not full.label_evidence_disputed
    assert disagreement.status == "DISAGREEMENT" and disagreement.label_evidence_disputed
    assert disagreement.human_review_required_before_promotion_evidence_use
    assert persist_fallback(full, artifact_root=tmp_path) != persist_fallback(
        disagreement, artifact_root=tmp_path
    )
    assert (
        path.read_bytes() == before and len(full.comparisons) == len(disagreement.comparisons) == 10
    )
    with pytest.raises(ValueError, match="RECONCILIATION_PENDING"):
        reconcile_openfootball(value, snapshot=openfootball_for(value, missing=True), audited_at=AT)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.openligadb.de/getresulttypes",
        "https://fantasy.premierleague.com/api/bootstrap-static/",
        "https://api.the-odds-api.com/v4/sports",
        "https://www.premierleague.com/results",
        "https://api.openligadb.de/getmatchdata/bl1/2026",
        "https://user:x@api.openligadb.de/getresulttypes",
        "https://api.openligadb.de/getresulttypes?token=x",
    ],
)
def test_t19_transport_refuses_undeclared_hosts_routes_credentials(url):
    with pytest.raises(ValueError, match="undeclared"):
        acquisition.HttpOpenLigaTransport().get(url)


def test_t14_t19_installed_public_context_command_is_offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("unexpected provider access")

    monkeypatch.setattr(acquisition.HttpOpenLigaTransport, "get", denied)
    result = CliRunner().invoke(app, ["events", "team-strength", "p01-fallback", "context"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["semantic_sha256"] == CONTEXT_SHA and payload["source"] == "OpenLigaDB"


def review_fixture(tmp_path):
    root = tmp_path / "implementation"
    files = []
    for relative in acquisition.REVIEWED_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        body = ("SYNTHETIC_REVIEW_FIXTURE " + relative).encode()
        path.write_bytes(body)
        files.append(
            acquisition.ReviewedFile(path=relative, byte_sha256=hashlib.sha256(body).hexdigest())
        )
    review = seal(
        acquisition.P01IndependentReview,
        context_sha256=CONTEXT_SHA,
        reviewer_identity="SYNTHETIC_UNIT_TEST_NOT_A_LIVE_CLEARANCE",
        reviewed_at=load_context().amended_at + timedelta(seconds=1),
        verdict="CLEAR_FOR_P01_OPENLIGADB_DESCRIPTIVE_SCORING",
        files=tuple(files),
        assessment=("Synthetic gate fixture only",) * 8,
    )
    path = tmp_path / "review.json"
    path.write_text(review.model_dump_json(), encoding="utf-8")
    return root, path, review


def test_t08_review_sha_file_bytes_and_chronology_authentication(tmp_path):
    root, path, review = review_fixture(tmp_path)
    assert (
        acquisition.authenticate_review(
            path, expected_sha256=review.semantic_sha256, implementation_root=root
        )
        == review
    )
    with pytest.raises(ValueError):
        acquisition.authenticate_review(path, expected_sha256="0" * 64, implementation_root=root)
    (root / acquisition.REVIEWED_PATHS[-1]).write_text("changed after review")
    with pytest.raises(ValueError, match="changed after independent review"):
        acquisition.authenticate_review(
            path, expected_sha256=review.semantic_sha256, implementation_root=root
        )
    payload = json.loads(path.read_bytes())
    payload["reviewed_at"] = "2026-10-01T00:00:00Z"
    payload["semantic_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "semantic_sha256"}
    )
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="predates A02"):
        acquisition.authenticate_review(
            path, expected_sha256=payload["semantic_sha256"], implementation_root=root
        )


def test_t08_t09_t19_one_attempt_projection_and_review_before_transport(tmp_path, monkeypatch):
    # Only synthetic authority is substituted here; numerical and provider
    # admission paths are real. Operational authority remains literal-pinned.
    root, review_path, review = review_fixture(tmp_path)
    context = synthetic_context()
    monkeypatch.setattr(acquisition, "load_context", lambda: context)
    authenticate_calls = []

    def authenticate_synthetic(path):
        authenticate_calls.append(path)
        return ten_forecast()

    monkeypatch.setattr(acquisition, "authenticate_p01", authenticate_synthetic)
    calls = []
    bodies = dict(
        zip(
            context.allowed_routes,
            (GLOBAL, LEAGUE, json.dumps(provider_rows()).encode()),
            strict=True,
        )
    )

    class Transport:
        def get(self, url):
            assert authenticate_calls
            assert (tmp_path / "retained/OPENLIGADB-P01-ONE-ATTEMPT.json").is_file()
            calls.append(url)
            return bodies[url]

    args = dict(
        forecast_path=tmp_path / "synthetic-forecast",
        review_path=review_path,
        expected_review_sha256=review.semantic_sha256,
        implementation_root=root,
        artifact_root=tmp_path / "retained",
        transport=Transport(),
        clock=lambda: datetime(2026, 10, 17, tzinfo=UTC),
    )
    with pytest.raises(ValueError):
        acquisition.acquire_p01_once(**(args | {"expected_review_sha256": "0" * 64}))
    assert calls == [] and not (tmp_path / "retained").exists()
    with pytest.raises(ValueError, match="predates independent review"):
        acquisition.acquire_p01_once(
            **(args | {"clock": lambda: datetime(2026, 10, 5, tzinfo=UTC)})
        )
    assert calls == []
    admitted = acquisition.acquire_p01_once(**args)
    assert calls == list(context.allowed_routes)
    assert (
        len(admitted.outcomes) == 10
        and admitted.independent_review_sha256 == review.semantic_sha256
    )
    assert admitted.independently_reviewed_at == review.reviewed_at
    retained = list((tmp_path / "retained").rglob("*.json"))
    assert len(retained) == 2
    assert all("MUST_NOT_BE_RETAINED" not in path.read_text() for path in retained)
    assert all(path.read_bytes() != body for path in retained for body in bodies.values())
    with pytest.raises(ValueError, match="ONE_ATTEMPT_CONSUMED"):
        acquisition.acquire_p01_once(**args)
    assert calls == list(context.allowed_routes)


@pytest.mark.parametrize("failure", ["unfinished", "bad_metadata"])
def test_t08_incomplete_acquisition_consumes_attempt_without_partial_artifact(
    tmp_path, monkeypatch, failure
):
    root, review_path, review = review_fixture(tmp_path)
    monkeypatch.setattr(acquisition, "load_context", synthetic_context)
    monkeypatch.setattr(acquisition, "authenticate_p01", lambda path: ten_forecast())
    rows = provider_rows()
    rows[0]["matchIsFinished"] = False
    bodies = [GLOBAL, b"[]" if failure == "bad_metadata" else LEAGUE, json.dumps(rows).encode()]
    calls = []

    class Transport:
        def get(self, url):
            calls.append(url)
            return bodies[len(calls) - 1]

    args = dict(
        forecast_path=tmp_path / "synthetic",
        review_path=review_path,
        expected_review_sha256=review.semantic_sha256,
        implementation_root=root,
        artifact_root=tmp_path / "retained",
        transport=Transport(),
        clock=lambda: datetime(2026, 10, 17, tzinfo=UTC),
    )
    with pytest.raises(ValueError):
        acquisition.acquire_p01_once(**args)
    assert len(calls) == (2 if failure == "bad_metadata" else 3)
    assert len(list((tmp_path / "retained").rglob("*.json"))) == 1
    with pytest.raises(ValueError, match="ONE_ATTEMPT_CONSUMED"):
        acquisition.acquire_p01_once(**args)


@pytest.mark.parametrize("bad", [-1, True, "2", 37])
def test_t10_shared_kernel_refuses_invalid_indices(bad):
    with pytest.raises(ValueError):
        score_public_fixture_labels(frozen().forecasts[0], hg=bad, ag=1)


def test_t18_rehashed_false_reconciliation_claim_rejected():
    value = labels()
    disputed = reconcile_openfootball(
        value, snapshot=openfootball_for(value, changed=True), audited_at=AT
    )
    payload = json.loads(disputed.model_dump_json())
    payload["comparisons"][0]["agrees"] = True
    payload["label_evidence_disputed"] = False
    payload["status"] = "FULL_RECONCILIATION"
    payload["semantic_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "semantic_sha256"}
    )
    with pytest.raises(ValueError):
        P01FallbackReconciliationV1.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "failure",
    [
        "ok",
        "redirect",
        "http_error",
        "content_type",
        "length",
        "oversize",
        "truncated",
        "timeout",
        "socket_error",
    ],
)
def test_t19_transport_bounded_no_redirect_no_retry(monkeypatch, failure):
    body = b"[]" if failure != "oversize" else b"x" * 524289
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    if failure == "length":
        headers["Content-Length"] = "524289"
    elif failure == "truncated":
        headers["Content-Length"] = "10"
    elif failure == "content_type":
        headers["Content-Type"] = "text/html"
    elif failure == "oversize":
        headers.pop("Content-Length")

    class Response:
        status = 302 if failure == "redirect" else 500 if failure == "http_error" else 200
        offset = 0

        def getheader(self, key, default=None):
            return headers.get(key, default)

        def read1(self, size):
            part = body[self.offset : self.offset + size]
            self.offset += len(part)
            return part

    class Connection:
        sock = None

        def __init__(self):
            self.requests = []
            self.closed = False

        def request(self, *args, **kwargs):
            self.requests.append((args, kwargs))
            if failure == "socket_error":
                raise OSError("synthetic failure")

        def getresponse(self):
            return Response()

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(
        acquisition.http.client, "HTTPSConnection", lambda *args, **kwargs: connection
    )
    if failure == "timeout":
        times = iter((0, 21))
        monkeypatch.setattr(acquisition.time, "monotonic", lambda: next(times))
    if failure == "ok":
        assert acquisition.HttpOpenLigaTransport().get(load_context().allowed_routes[0]) == b"[]"
    else:
        with pytest.raises(ValueError):
            acquisition.HttpOpenLigaTransport().get(load_context().allowed_routes[0])
    assert len(connection.requests) == 1 and connection.closed


def test_t14_public_cli_score_report_reconcile_keeps_provenance(tmp_path, monkeypatch):
    from dmf_pulse.cli import p01_fallback as commands

    value = labels()
    labels_path = persist_fallback(value, artifact_root=tmp_path)
    authenticated_forecasts = []

    def synthetic_forecast(path):
        authenticated_forecasts.append(path)
        return ten_forecast()

    # CLI I/O uses explicitly synthetic authority; production pin rejection is
    # independently tested above. The actual typed admission/kernel runs here.
    monkeypatch.setattr(commands, "authenticate_p01", synthetic_forecast)
    monkeypatch.setattr(commands, "score_p01_fallback", _score_admitted)
    monkeypatch.setattr(commands, "load_context", synthetic_context)
    base = ["events", "team-strength", "p01-fallback"]
    runner = CliRunner()
    args = [
        "--outcomes",
        str(labels_path),
        "--outcomes-sha256",
        value.semantic_sha256,
        "--artifact-root",
        str(tmp_path),
    ]
    result = runner.invoke(app, [*base, "score", "--forecast", str(tmp_path / "synthetic"), *args])
    assert result.exit_code == 0, result.stdout
    score = json.loads(result.stdout)
    assert (
        score["provenance"] == "PUBLIC_FALLBACK_OUTCOME_SOURCE"
        and len(authenticated_forecasts) == 2
    )
    score_path = tmp_path / score["schema_version"] / (score["semantic_sha256"] + ".json")
    report_args = ["--score", str(score_path), "--score-sha256", score["semantic_sha256"]]
    result = runner.invoke(app, [*base, "report", *report_args, *args])
    assert result.exit_code == 0, result.stdout
    report = json.loads(result.stdout)
    assert report["provenance"] == report["score"]["provenance"] == "PUBLIC_FALLBACK_OUTCOME_SOURCE"
    assert report["score"]["context"]["evaluation_epoch"] == "EVALUATION_EPOCH_003"
    snapshot = tmp_path / "openfootball.json"
    snapshot.write_text(openfootball_for(value).model_dump_json(), encoding="utf-8")
    result = runner.invoke(app, [*base, "reconcile", "--openfootball", str(snapshot), *args])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "FULL_RECONCILIATION"
    wrong_labels = [
        "--outcomes",
        str(score_path),
        "--outcomes-sha256",
        score["semantic_sha256"],
        "--artifact-root",
        str(tmp_path),
    ]
    assert (
        runner.invoke(
            app, [*base, "score", "--forecast", str(tmp_path / "synthetic"), *wrong_labels]
        ).exit_code
        != 0
    )
    assert runner.invoke(app, [*base, "report", *report_args, *wrong_labels]).exit_code != 0
    assert (
        runner.invoke(
            app, [*base, "reconcile", "--openfootball", str(snapshot), *wrong_labels]
        ).exit_code
        != 0
    )


def test_t01_no_fit_freeze_or_draw_generation_in_frozen_view_or_fallback_scoring(monkeypatch):
    from dmf_pulse.evaluation import team_strength_prospective as prospective
    from dmf_pulse.evaluation.p01_frozen_view import _read_pinned_representation
    from dmf_pulse.football_events import team_strength_adapter as adapter
    from dmf_pulse.football_events import team_strength_mixture as mixture
    from dmf_pulse.football_events import team_strength_model as model
    from dmf_pulse.football_events import team_strength_parameter_draws as draws

    forecast, outcomes = ten_forecast(), labels()
    raw = forecast.model_dump_json().encode()
    expected_scores = scored().metrics.scores

    def denied(*args, **kwargs):
        raise AssertionError("fit/freeze/draw regeneration forbidden for frozen P01 scoring")

    for module, names in (
        (
            prospective,
            (
                "_fixture_forecast",
                "freeze_public_team_forecasts",
                "freeze_public_forecast_request",
                "joint_parameter_draws",
                "authenticate_parameter_draws",
                "fixture_draw_rates",
                "fixture_prior_bundle",
            ),
        ),
        (draws, ("joint_parameter_draws", "authenticate_parameter_draws")),
        (model, ("fit_team_strength", "fit_strength", "fit_cohort_season", "historical_cohort")),
        (mixture, ("fixture_draw_rates",)),
        (adapter, ("fixture_prior_bundle",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, denied)
    view = _read_pinned_representation(
        raw,
        expected_byte_sha256=hashlib.sha256(raw).hexdigest(),
        expected_semantic_sha256=forecast.semantic_sha256,
    )
    assert view.model_dump(mode="json") == forecast.model_dump(mode="json")
    require_forecast_binding(view, context=outcomes.context)
    assert _score_admitted(view, outcomes=outcomes, as_of=AT).metrics.scores == expected_scores
    with pytest.raises(ValueError):
        _read_pinned_representation(
            raw, expected_byte_sha256="0" * 64, expected_semantic_sha256=forecast.semantic_sha256
        )
    with pytest.raises(ValueError):
        score_p01_fallback(forecast, outcomes=outcomes, as_of=AT)
