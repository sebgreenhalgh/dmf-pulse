"""Build the Stage-12 review wheel without resolving network dependencies.

This is an evidence fallback for restricted review workspaces. The repository's canonical build
remains Hatchling via ``uv build`` and must be repeated by the independent reviewer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def build(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eval-012-wheel-") as temporary:
        work = Path(temporary)
        shutil.copytree(ROOT / "src", work / "src")
        shutil.copy2(ROOT / "README.md", work / "README.md")
        shutil.copy2(ROOT / "LICENSE", work / "LICENSE")
        (work / "setup.py").write_text(
            """from setuptools import find_packages, setup

setup(
    name="dmf-pulse",
    version="0.2.0",
    description="Governed foundation for the private DMF Pulse decision engine",
    packages=find_packages("src"),
    package_dir={"": "src"},
    package_data={"dmf_pulse": ["py.typed"], "dmf_pulse.evaluation": ["resources/*.yaml"]},
    include_package_data=True,
    python_requires=">=3.13,<3.14",
    install_requires=["pydantic>=2,<3", "PyYAML>=6,<7", "typer>=0.12,<1"],
    entry_points={"console_scripts": ["dmf=dmf_pulse.cli.app:main"]},
)
""",
            encoding="utf-8",
        )
        environment = dict(os.environ)
        environment["SOURCE_DATE_EPOCH"] = "1786947236"
        subprocess.run(
            [sys.executable, "setup.py", "--no-user-cfg", "bdist_wheel", "--dist-dir", str(output)],
            cwd=work,
            env=environment,
            check=True,
        )
    wheels = sorted(output.glob("dmf_pulse-0.2.0-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel, found {wheels}")
    return wheels[0]


if __name__ == "__main__":
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    print(build(destination))
