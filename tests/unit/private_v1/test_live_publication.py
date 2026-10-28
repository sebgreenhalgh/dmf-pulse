"""The manual transient entry point shares the official-deadline publication gate."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from dmf_pulse.cli import private_v1
from dmf_pulse.cli.app import app
from dmf_pulse.private_v1.actionability import DeadlineGuard
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.live import PrivateV1LiveTransientService
from tests.unit.private_v1.test_live_transient import _boundary_request

NOW = datetime(2026, 8, 30, 10, tzinfo=UTC)
DEADLINE = NOW + timedelta(hours=1)


@pytest.mark.parametrize(
    "time,expected",
    [
        (NOW - timedelta(hours=1), "DECISION_CLOCK_INVALID"),
        (DEADLINE, "DECISION_DEADLINE_PASSED"),
        (NOW.replace(tzinfo=None), "DECISION_CLOCK_INVALID"),
    ],
)
def test_manual_source_usable_time_and_deadline_are_enforced(time, expected):
    class Fpl:
        def compile(self, request):
            return SimpleNamespace(
                provenance=SimpleNamespace(usable_at=NOW),
                target_event=SimpleNamespace(deadline_at=DEADLINE),
            )

    with pytest.raises(PrivateV1Error) as failure:
        PrivateV1LiveTransientService(fpl_service=Fpl(), clock=lambda: time).run(
            _boundary_request()
        )
    assert failure.value.code == expected


@pytest.mark.parametrize("expired", [False, True])
def test_manual_public_cli_checks_publication_without_writing(
    repository_root, tmp_path, monkeypatch, expired
):
    source = tmp_path / "synthetic.json"
    source.write_text("{}", encoding="utf-8")
    report = "SYNTHETIC_PRIVATE_ACTION"
    receipt = DeadlineGuard(lambda: NOW).bind(
        deadline_at=DEADLINE, decision_sha256="a" * 64, report=report
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return DEADLINE if expired else NOW

    monkeypatch.setattr(private_v1, "datetime", Clock)
    monkeypatch.setattr(
        private_v1,
        "load_private_input_model",
        lambda *args, **kwargs: SimpleNamespace(score_priors=(), fixtures=()),
    )
    monkeypatch.setattr(private_v1, "load_mc_policy", lambda path: None)
    monkeypatch.setattr(
        private_v1.PrivateV1LiveTransientService,
        "run",
        lambda *args: SimpleNamespace(
            report=report,
            actionability=receipt,
            publication_not_before=NOW,
            decision=SimpleNamespace(semantic_sha256="a" * 64),
        ),
    )
    args = ["private-v1", "live-transient"]
    for option in (
        "bootstrap",
        "fixtures",
        "manager",
        "odds-input",
        "team-alias-plan",
        "fixture-mapping-plan",
        "market-identity-view",
        "player-identity-map",
        "score-priors",
        "stage7",
        "ownership",
        "candidate-policy",
        "mc-policy",
    ):
        args += ["--" + option, str(source)]
    for option in ("rules-approved-at", "captured-at", "information-cutoff", "mapping-decided-at"):
        args += ["--" + option, NOW.isoformat()]
    args += [
        "--ruleset",
        str(repository_root / "config/rules/fpl-2026-27"),
        "--rules-approval-reference",
        "SYNTHETIC_TEST_ONLY",
        "--gameweek",
        "2",
        "--run-id",
        "SYNTHETIC_TEST_ONLY",
        "--code-sha",
        "a" * 40,
        "--root-seed",
        "42",
        "--scenario-count",
        "1",
    ]
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = CliRunner().invoke(app, args)
    assert result.exit_code == (2 if expired else 0), result.output
    if expired:
        assert "DECISION_DEADLINE_PASSED" in result.stdout
        assert report not in result.output
    else:
        assert result.stdout == report
    assert before == {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }
