"""The explicit analytical exception never authorizes a SQLite control plane."""

from pathlib import Path

import pytest

from scripts.validate_repository import _validate_dat_repository_contract


def root(tmp_path, *, authorized=True):
    (tmp_path / "compose.test.yaml").write_bytes(Path("compose.test.yaml").read_bytes())
    if authorized:
        path = tmp_path / "tickets/OPR-004/REQUEST.txt"
        path.parent.mkdir(parents=True)
        path.write_bytes(Path("tickets/OPR-004/REQUEST.txt").read_bytes())
    return tmp_path


@pytest.mark.parametrize("name", ["analysis_store.py", "analysis_cli.py"])
def test_exact_authorized_stdlib_modules_are_permitted(tmp_path, name):
    directory = root(tmp_path) / "src/dmf_pulse/operation"
    directory.mkdir(parents=True)
    (directory / name).write_text("import sqlite3\n", encoding="utf-8")
    errors = []
    _validate_dat_repository_contract(tmp_path, errors)
    assert errors == []


@pytest.mark.parametrize(
    "name,body",
    [
        ("control.py", "import sqlite3\n"),
        ("analysis_store.py", 'URL="sqlite:///control.db"\n'),
        ("analysis_cli.py", 'URL="sqlite+pysqlite:///control.db"\n'),
        ("standing.py", "from sqlite3 import connect\n"),
    ],
)
def test_analysis_permission_does_not_spread_to_controls_or_drivers(tmp_path, name, body):
    directory = root(tmp_path) / "src/dmf_pulse/operation"
    directory.mkdir(parents=True)
    (directory / name).write_text(body, encoding="utf-8")
    errors = []
    _validate_dat_repository_contract(tmp_path, errors)
    assert len(errors) == 1 and "prohibited SQLite" in errors[0]


def test_missing_or_changed_owner_request_does_not_enable_exception(tmp_path):
    directory = root(tmp_path, authorized=False) / "src/dmf_pulse/operation"
    directory.mkdir(parents=True)
    (directory / "analysis_store.py").write_text("import sqlite3\n", encoding="utf-8")
    for changed in (False, True):
        if changed:
            request = tmp_path / "tickets/OPR-004/REQUEST.txt"
            request.parent.mkdir(parents=True)
            request.write_text("unreviewed request", encoding="utf-8")
        errors = []
        _validate_dat_repository_contract(tmp_path, errors)
        assert any("prohibited SQLite" in error for error in errors)


def test_database_artifacts_still_cannot_enter_the_repository(tmp_path):
    root(tmp_path)
    (tmp_path / "control.sqlite").write_bytes(b"owned-test-not-a-real-database")
    errors = []
    _validate_dat_repository_contract(tmp_path, errors)
    assert errors == ["prohibited SQLite file exists: control.sqlite"]
