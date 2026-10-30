"""Only the exact inherited Wave005 path extends the historical span bound."""

import runpy
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_exact_wave005_inherited_four_revision_path():
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[3] / "scripts/test_migration_matrix.py")
    )
    plan = module["_revision_plan"]("20260803_0005", "head")
    assert plan.target == "20261030_0009"
    assert plan.revisions == ("20260807_0006", "20261029_0007", "20261029_0008", "20261030_0009")
    assert len(module["_revision_plan"]("20260807_0006", "head").revisions) == 3


@pytest.mark.parametrize("baseline", ["20260724_0002", "20260725_0004", "20261030_0009"])
def test_other_extended_or_empty_paths_remain_refused(baseline):
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[3] / "scripts/test_migration_matrix.py")
    )
    with pytest.raises(module["MatrixError"], match="reviewed ordered revision"):
        module["_revision_plan"](baseline, "head")
