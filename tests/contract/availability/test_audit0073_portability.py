from __future__ import annotations

import hashlib
import json
from pathlib import Path


def test_approved_mapping_and_root_schema_are_byte_frozen(repository_root: Path) -> None:
    expected = {
        "fixtures/availability/MIN-007/external_mapping_plan.json": "490585bed1bce6f9d904ddb12b6df6b6a4d04caca91fb1160af53e83578a3550",
        "public_contracts/probability.schema.json": "6a0dcfb79f5e8939dd54f889b61236783d8c4e05a4bd0272eae25599c2373f9b",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((repository_root / relative).read_bytes()).hexdigest() == digest
    root_schema = (repository_root / "public_contracts/probability.schema.json").read_bytes()
    assert (
        root_schema
        == (repository_root / "public_contracts/min007g/probability.schema.json").read_bytes()
    )
    assert (
        json.loads(root_schema)["$id"]
        == "https://dmf-pulse.local/contracts/min-007/probability.schema.json"
    )


def test_g_goldens_are_repository_contained(repository_root: Path) -> None:
    forbidden = ("dmf-pulse-context", "CodexPacks", "C:" + "\\Users\\")
    paths = (
        *sorted((repository_root / "tests/golden/availability").glob("*.py")),
        *sorted((repository_root / "tests/contract/availability").glob("*.py")),
        *sorted((repository_root / "tests/integration/availability").glob("*.py")),
    )
    for path in paths:
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8")
        assert not any(value in text for value in forbidden), path
    contexts = repository_root / "fixtures/availability/MIN-007G/contexts"
    assert {path.stem for path in contexts.glob("*.json")} == {
        "stable_xi",
        "high_rotation",
        "hard_ineligible",
        "new_signing",
        "promoted_team",
        "new_manager",
        "rare_bench_60_plus",
        "goalkeeper",
        "insufficient_eligible_squad",
    }
