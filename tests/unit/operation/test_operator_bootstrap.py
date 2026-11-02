"""Independent bootstrap arguments and real pre-main spawn import regression."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
BOOTSTRAP = Path(__file__).resolve().parents[3] / "scripts/operator_launcher.py"


def bootstrap():
    module = types.ModuleType("owned_operator_bootstrap_review")
    module.__file__ = str(BOOTSTRAP)
    exec(compile(BOOTSTRAP.read_bytes(), str(BOOTSTRAP), "exec"), module.__dict__)
    return module


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["start"],
        ["operation", "withdraw-standing"],
        ["operation", "rollback-reviewed-update", "a" * 64],
    ],
)
def test_only_finite_reviewed_actions_are_admitted(arguments):
    assert bootstrap().approved_arguments(arguments) == (arguments or ["start"])


def test_maintenance_carrier_must_be_absolute(tmp_path):
    value = ["operation", "install-reviewed-update", str(tmp_path / "owned-carrier")]
    assert bootstrap().approved_arguments(value) == value


@pytest.mark.parametrize(
    "arguments",
    [
        ["start", "extra"],
        ["--help"],
        ["operation", "run"],
        ["operation", "install-reviewed-update", "relative"],
        ["operation", "rollback-reviewed-update", "A" * 64],
        ["operation", "rollback-reviewed-update", "a" * 63],
        ["operation", "withdraw-standing", "extra"],
    ],
)
def test_arguments_cannot_expand_execution_scope(arguments):
    with pytest.raises(ValueError):
        bootstrap().approved_arguments(arguments)


def test_preparation_filters_child_paths_without_changing_parent(monkeypatch):
    from multiprocessing import spawn

    paths = [
        "/trusted/Lib",
        "/owned/site-packages",
        r"C:\owned\SITE-PACKAGES",
        "/owned/dist-packages",
        "/trusted/package-site-packages-data",
    ]
    monkeypatch.setattr(spawn, "get_preparation_data", lambda _: {"sys_path": list(paths)})
    parent_path = list(sys.path)
    bootstrap().protect_worker_preparation()
    assert spawn.get_preparation_data("owned")["sys_path"] == [paths[0], paths[-1]]
    assert sys.path == parent_path


@pytest.mark.parametrize("protected", [False, True])
def test_real_spawn_cannot_import_site_pkgutil_before_main_filter(tmp_path, protected):
    """The unprotected control must reproduce; the actual wrapper must close it."""
    source = Path(sysconfig.get_path("stdlib")) / "pkgutil.py"
    assert source.is_file()
    driver = tmp_path / "owned_spawn.py"
    site = tmp_path / "site-packages"
    site.mkdir()
    marker = tmp_path / "owned-pre-main-marker.txt"
    (site / "pkgutil.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('OWNED_PRE_MAIN_IMPORT', encoding='utf-8')\n"
        f"exec(compile(Path({str(source)!r}).read_bytes(), {str(source)!r}, 'exec'), globals())\n",
        encoding="utf-8",
    )
    driver.write_text(
        "import sys\n"
        "if __name__ == '__mp_main__':\n"
        "    sys.path[:] = [p for p in sys.path if 'site-packages' not in p.replace(chr(92),'/').casefold().split('/')]\n"
        "import json, multiprocessing, types\n"
        "from pathlib import Path\n"
        "def worker():\n"
        "    return None\n"
        "if __name__ == '__main__':\n"
        f"    path=Path({str(BOOTSTRAP)!r})\n"
        "    module=types.ModuleType('owned_bootstrap_integration')\n"
        "    module.__file__=str(path)\n"
        "    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)\n"
        + ("    module.protect_worker_preparation()\n" if protected else "")
        + f"    sys.path.insert(0, {str(site)!r})\n"
        "    child=multiprocessing.get_context('spawn').Process(target=worker)\n"
        "    child.start()\n"
        "    child.join(timeout=15)\n"
        "    if child.is_alive():\n"
        "        child.terminate(); child.join(timeout=5); raise ValueError('OWNED_CHILD_TIMEOUT')\n"
        f"    print(json.dumps({{'child_exit_code':child.exitcode,'marker':Path({str(marker)!r}).is_file(),'isolated':bool(sys.flags.isolated),'no_site':bool(sys.flags.no_site),'no_bytecode':bool(sys.flags.dont_write_bytecode)}}))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(driver)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=25,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value == {
        "child_exit_code": 0,
        "marker": not protected,
        "isolated": True,
        "no_site": True,
        "no_bytecode": True,
    }
    assert not tuple(site.rglob("*.pyc"))
    assert os.name in {"nt", "posix"}
