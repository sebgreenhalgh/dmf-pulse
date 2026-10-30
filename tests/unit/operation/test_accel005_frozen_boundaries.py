"""The exact approved annotation/permission seams preserve all retained behavior."""

import ast
import subprocess
from pathlib import Path

import pytest

from tests.accel005_legacy_freeze_support import without_accel005_permission

pytestmark = pytest.mark.unit
PARENT = "f07c063b4f6e4cb8451b9189771a0410329f23f0"


@pytest.mark.parametrize("name,unions", [("client", 3), ("transient", 1)])
def test_quota_addition_is_import_and_input_annotations_only(name, unions):
    path = f"src/dmf_pulse/ingestion/odds/{name}.py"
    original = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], text=True, timeout=30)

    class RemoveReviewedQuota(ast.NodeTransformer):
        def __init__(self):
            self.imports = 0
            self.unions = 0

        def visit_ImportFrom(self, node):
            if node.module == "dmf_pulse.ingestion.odds.models":
                self.imports += sum(alias.name == "QualifiedOperatorQuota" for alias in node.names)
                node.names = [
                    alias for alias in node.names if alias.name != "QualifiedOperatorQuota"
                ]
            return node

        def visit_arg(self, node):
            annotation = node.annotation
            if (
                node.arg == "quota"
                and isinstance(annotation, ast.BinOp)
                and isinstance(annotation.op, ast.BitOr)
                and isinstance(annotation.right, ast.Constant)
                and annotation.right.value is None
                and isinstance(annotation.left, ast.BinOp)
                and isinstance(annotation.left.op, ast.BitOr)
                and isinstance(annotation.left.left, ast.Name)
                and annotation.left.left.id == "QuotaState"
                and isinstance(annotation.left.right, ast.Name)
                and annotation.left.right.id == "QualifiedOperatorQuota"
            ):
                self.unions += 1
                node.annotation = ast.BinOp(
                    left=annotation.left.left, op=ast.BitOr(), right=annotation.right
                )
            return node

    visitor = RemoveReviewedQuota()
    current = visitor.visit(ast.parse(Path(path).read_text(encoding="utf-8")))
    assert (visitor.imports, visitor.unions) == (1, unions)
    assert ast.dump(current) == ast.dump(ast.parse(original))
    moved = (
        Path(path)
        .read_text(encoding="utf-8")
        .replace("quota: QuotaState | QualifiedOperatorQuota | None", "quota: QuotaState | None", 1)
    )
    moved += "\ndef unreviewed_runtime_union(value):\n    return value | QualifiedOperatorQuota\n"
    altered = visitor.visit(ast.parse(moved))
    assert ast.dump(altered) != ast.dump(ast.parse(original))


@pytest.mark.parametrize("name", ["team_strength_live", "team_strength_live_network"])
def test_native_permission_seam_normalizer_cannot_hide_other_changes(name):
    path = f"src/dmf_pulse/private_v1/{name}.py"
    source = Path(path).read_text(encoding="utf-8")
    original = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], text=True, timeout=30)
    assert without_accel005_permission(source, path) == original
    assert without_accel005_permission(source + "\nUNREVIEWED_CONTROL = True\n", path) != original
    with pytest.raises(ValueError, match="seam changed"):
        without_accel005_permission(
            source.replace("requires_supplier_permission", "unreviewed_permission")
            if name.endswith("network")
            else source.replace("self._fpl_transport is None", "True"),
            path,
        )
