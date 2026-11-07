"""Build the programme's capped, source-safe review packet with detached digests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    output = root / "review_pack/DMF-MODEL-QUALITY-001"
    output.mkdir(parents=True, exist_ok=True)
    base = "df26ab0723dea99469fe4c98423402ea91f85776"

    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, timeout=60
        ).stdout

    def require(condition: bool, code: str) -> None:
        if not condition:
            raise ValueError(code)

    require(
        not git("status", "--porcelain=v1", "--untracked-files=all").strip(),
        "REVIEW_CLEAN_TREE_REQUIRED",
    )
    head = git("rev-parse", "HEAD").decode().strip()
    changed = git("diff", "--name-only", base, "HEAD").decode().splitlines()

    def read(path: str) -> bytes:
        return git("show", f"{head}:{path}")

    def log(name: str) -> bytes:
        return read(f"evidence/tickets/DMF-MODEL-QUALITY-001/{name}")

    def digest(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()

    files = {
        "01_INDEX.md": (
            "# DMF-MODEL-QUALITY-001 research review\n\n"
            f"Baseline `{base}`. Review head `{head}`.\n\n"
            "Read status, executive report, source audit and changed source. "
            "This packet contains source and owned evidence only. "
            "Real GW10 findings remain private. No production activation.\n"
        ).encode(),
        "02_STATUS.json": log("checkpoint.json"),
        "04_CHANGES.patch": git("diff", "--binary", base, "HEAD"),
        "05_CHANGED_FILES.txt": ("\n".join(changed) + "\n").encode(),
        "06_AUTHORITY.json": log("authority_register.json"),
        "07_EXECUTIVE.md": read("docs/operation/MODEL-QUALITY-001-EXECUTIVE.md"),
        "08_CURRENT_MODEL.md": read("docs/operation/MODEL-QUALITY-001-CURRENT.md"),
        "09_VALIDATION.md": read("docs/operation/MODEL-QUALITY-001-VALIDATION.md"),
        "10_CAPABILITY_MATRIX.csv": read("docs/operation/MODEL-QUALITY-001-GAPS.csv"),
        "11_ROADMAP.md": read("docs/operation/MODEL-QUALITY-001-ROADMAP.md"),
        "12_DICTIONARY_V2.md": read("docs/operation/ANALYSIS-DICTIONARY-v2.md"),
        "13_FOCUSED_TESTS.txt": log("final-focused.stdout.log")
        + b"\nINHERITED\n"
        + log("inherited-final.stdout.log"),
        "14_REVIEW.json": log("independent-review.json"),
        "15_GATES_AND_ATTEMPTS.json": json.dumps(
            {
                "gates": json.loads(log("checkpoint.json")),
                "attempts": json.loads(log("attempt-register.json")),
            },
            indent=2,
        ).encode(),
        "16_WHEEL.json": log("quality-wheel.json"),
        "17_SCOPE_AND_COVERAGE.json": log("scope-and-coverage.json"),
        "18_ACCEPTANCE.md": read("tickets/DMF-MODEL-QUALITY-001/ACCEPTANCE.md"),
        "19_CHANGED_PYTHON.txt": b"\n\n".join(
            ("FILE: " + path + "\n").encode() + read(path)
            for path in changed
            if path.endswith(".py")
        ),
    }
    files["03_MANIFEST.json"] = json.dumps(
        {
            "baseline": base,
            "head": head,
            "private_forecasts_included": False,
            "files": {
                name: {"sha256": digest(body), "bytes": len(body)}
                for name, body in sorted(files.items())
            },
        },
        indent=2,
    ).encode()
    files["20_SHA256SUMS.txt"] = "".join(
        f"{digest(body)}  {name}\n" for name, body in sorted(files.items())
    ).encode()
    require(
        len(files) == 20 and sum(map(len, files.values())) <= 32 * 1024 * 1024,
        "REVIEW_CAP_EXCEEDED",
    )
    require(
        all("/" not in name and "\\" not in name for name in files), "REVIEW_FLAT_NAMES_REQUIRED"
    )
    require(
        git("rev-parse", "HEAD").decode().strip() == head
        and not git("status", "--porcelain=v1", "--untracked-files=all").strip(),
        "REVIEW_SOURCE_CHANGED",
    )
    output = output / head[:12]
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "DMF_PULSE_DMF-MODEL-QUALITY-001_REVIEW.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as packet:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            packet.writestr(info, body, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as packet:
        require(
            packet.testzip() is None and set(packet.namelist()) == set(files), "REVIEW_ZIP_INVALID"
        )
        for name, body in files.items():
            require(packet.read(name) == body, "REVIEW_CONTENT_CHANGED")
        manifest = json.loads(packet.read("03_MANIFEST.json"))
        for name, row in manifest["files"].items():
            require(digest(packet.read(name)) == row["sha256"], "REVIEW_MANIFEST_DIGEST_INVALID")
        for line in packet.read("20_SHA256SUMS.txt").decode().splitlines():
            expected, name = line.split("  ", 1)
            require(digest(packet.read(name)) == expected, "REVIEW_DETACHED_DIGEST_INVALID")
    require(
        git("rev-parse", "HEAD").decode().strip() == head
        and not git("status", "--porcelain=v1", "--untracked-files=all").strip(),
        "REVIEW_SOURCE_CHANGED",
    )
    receipt = {
        "status": "PASS",
        "head": head,
        "files": 20,
        "payload_bytes": sum(map(len, files.values())),
        "archive_sha256": digest(archive.read_bytes()),
        "zip_crc_and_detached_digests_validated": True,
        "path": str(archive),
    }
    (output / "archive-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
