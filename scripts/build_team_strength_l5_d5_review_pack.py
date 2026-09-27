"""Explicit capped D5 source/offline evidence archive; no runtime collection."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICKET = "CURRENT-TEAM-STRENGTH-001P-L5-D5"
NAMES = (
    "config/optimisation/multi_gameweek.yaml",
    "scripts/build_team_strength_l5_d5_review_pack.py",
    "scripts/profile_live_scale_exact.py",
    "src/dmf_pulse/optimisation/multi_gameweek_errors.py",
    "src/dmf_pulse/optimisation/multi_gameweek_models.py",
    "src/dmf_pulse/optimisation/multi_gameweek_policy.py",
    "src/dmf_pulse/optimisation/multi_gameweek_service.py",
    "src/dmf_pulse/optimisation/multi_gameweek_solver.py",
    "src/dmf_pulse/private_v1/rolling.py",
    "src/dmf_pulse/private_v1/team_strength_diagnostics.py",
    "src/dmf_pulse/private_v1/team_strength_live_authority.py",
    "tests/unit/optimisation/test_multi_gameweek_solver.py",
    "tests/unit/optimisation/test_stage11_r7_layers.py",
    "tests/unit/private_v1/test_team_strength_d4_rolling_diagnostics.py",
    f"tickets/{TICKET}/HISTORICAL-L5-SAFE-RESULT.md",
    f"tickets/{TICKET}/ticket.yaml",
    f"evidence/tickets/{TICKET}/CAPACITY-ANALYSIS.md",
    f"evidence/tickets/{TICKET}/OFFLINE-ACCEPTANCE.md",
    f"evidence/tickets/{TICKET}/INDEPENDENT-REVIEW.md",
    f"evidence/tickets/{TICKET}/RESOURCE-LIMIT-AUDIT.md",
    f"evidence/tickets/{TICKET}/five-case-capacity.json",
    f"evidence/tickets/{TICKET}/generated-high-cap-reference.json",
    f"evidence/tickets/{TICKET}/generated-legacy-envelope-failure.json",
    f"evidence/tickets/{TICKET}/generated-near-envelope-capacity.json",
)


def build() -> dict[str, object]:
    if len(NAMES) != len(set(NAMES)) or len(NAMES) > 24:
        raise ValueError("D5 review entry cap exceeded")
    contents: dict[str, bytes] = {}
    for name in sorted(NAMES):
        path = ROOT / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("unsafe D5 review path")
        body = path.read_bytes()
        if len(body) > 1024 * 1024:
            raise ValueError("D5 review entry too large")
        contents[name] = body
    if sum(map(len, contents.values())) > 5 * 1024 * 1024:
        raise ValueError("D5 review payload too large")
    manifest = {
        "ticket": TICKET,
        "execution_mode": "OFFLINE_ONLY",
        "private_live_material": False,
        "files": [
            {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in contents.items()
        ],
    }
    output = ROOT / "review_pack" / f"{TICKET}.zip"
    output.parent.mkdir(exist_ok=True)
    if output.is_symlink() or not output.resolve().is_relative_to(ROOT):
        raise ValueError("unsafe D5 review destination")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in (
            *contents.items(),
            ("MANIFEST.json", json.dumps(manifest, sort_keys=True).encode()),
        ):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, body, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(output) as archive:
        if len(archive.namelist()) != len(contents) + 1:
            raise ValueError("D5 review entry count differs")
        for name, body in contents.items():
            if archive.read(name) != body:
                raise ValueError("D5 review verification failed")
    return {
        "status": "PASS",
        "files": len(contents) + 1,
        "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    print(json.dumps(build(), sort_keys=True))
