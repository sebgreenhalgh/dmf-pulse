"""Build the capped, root-only final EVAL-012 independent-review archive."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "4f1274ccef419a7c0bde335c48bd4070e248b2e6"
MAX_MEMBERS = 20
EVIDENCE = (
    "tickets/EVAL-012/ticket.yaml",
    "tickets/EVAL-012/ACCEPTANCE.md",
    "evidence/tickets/EVAL-012/TEST_RESULTS.json",
    "evidence/tickets/EVAL-012/VALIDATION_STATUS.md",
    "evidence/tickets/EVAL-012/COVERAGE.txt",
    "evidence/tickets/EVAL-012/BENCHMARK_RESULTS.json",
    "evidence/tickets/EVAL-012/LEAKAGE_ASSURANCE.json",
    "evidence/tickets/EVAL-012/REPLAY_ACCEPTANCE.json",
    "evidence/tickets/EVAL-012/CLI_ACCEPTANCE.json",
    "evidence/tickets/EVAL-012/BUILD_WHEEL_RESULT.txt",
    "evidence/tickets/EVAL-012/STATIC_ANALYSIS_STATUS.txt",
    "evidence/tickets/EVAL-012/FULL_REPOSITORY_TEST_STATUS.txt",
    "evidence/tickets/EVAL-012/TARGETED_REGRESSION_SCOPE.txt",
    "evidence/tickets/EVAL-012/ARTIFACT_ASSURANCE.txt",
    "evidence/tickets/EVAL-012/REPOSITORY_VALIDATION.txt",
    "evidence/tickets/EVAL-012/SCOPE_ASSURANCE.txt",
)


def _git(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(output: Path) -> Path:
    """Create and verify one deterministic, capped final review ZIP."""

    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eval-012-final-pack-") as temporary:
        work = Path(temporary)
        files: dict[str, bytes] = {
            "README.md": (
                "# EVAL-012 final independent-review pack\n\n"
                f"Base: `{BASE}`. Human acceptance, merge and accepted tag remain pending.\n"
            ).encode(),
            "PATCH.diff": _git("diff", "--binary", BASE, "--"),
            "CHANGED_FILES.txt": _git("diff", "--name-status", BASE, "--"),
        }
        for relative in EVIDENCE:
            source = ROOT / relative
            name = source.name
            if name in files:
                name = f"{source.parent.name}_{name}"
            files[name] = source.read_bytes()
        if len(files) + 1 > MAX_MEMBERS:
            raise RuntimeError("Stage-12 review pack exceeds the 20-member cap")
        pack = "".join(f"{_sha256(data)}  {name}\n" for name, data in sorted(files.items()))
        files["PACK.sha256"] = pack.encode("ascii")
        for name, data in files.items():
            (work / name).write_bytes(data)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, files[name])
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        if len(names) > MAX_MEMBERS or any(Path(name).name != name for name in names):
            raise RuntimeError("final review pack is not capped and root-only")
        packed = archive.read("PACK.sha256").decode("ascii").splitlines()
        expected = {
            name: digest for digest, name in (line.split("  ", maxsplit=1) for line in packed)
        }
        for name, digest in ((name, _sha256(archive.read(name))) for name in names):
            if name != "PACK.sha256" and expected.get(name) != digest:
                raise RuntimeError(f"final review pack hash mismatch: {name}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    result = build(arguments.output)
    print(f"PASS path={result} members=20 sha256={_sha256(result.read_bytes())}")


if __name__ == "__main__":
    main()
