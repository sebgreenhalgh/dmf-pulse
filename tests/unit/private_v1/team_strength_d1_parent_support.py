"""Read only exact committed parent code; replay genuine synthetic solve outputs."""

import ast
import subprocess
import sys
from types import ModuleType

PARENT = "06cbd10719fee3cde87dbb2f9698d81567672618"


def parent_source(repository_root, relative):
    return subprocess.run(
        ["git", "show", f"{PARENT}:{relative}"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout


def assert_parent_success(repository_root, prepared, preparation, runs, current):
    from dmf_pulse.private_v1 import team_strength_comparison as implementation

    source = parent_source(repository_root, "src/dmf_pulse/private_v1/team_strength_comparison.py")
    module = ModuleType("_d1_immutable_parent_comparison")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, "<immutable-parent-comparison>", "exec"), module.__dict__)
        original = module._compare_runs(prepared, preparation.shadow_input, *runs)
        # Explicit human authorization: only work-budget identity/containing hashes change.
        for old, new in zip(original.worlds, current.worlds, strict=True):
            assert old.signature == new.signature
            assert dict(old.controls)["work_budget"] != dict(new.controls)["work_budget"]
            assert {k: v for k, v in old.controls if k != "work_budget"} == {
                k: v for k, v in new.controls if k != "work_budget"
            }
        module._controls = implementation._controls
        authorized = module._compare_runs(prepared, preparation.shadow_input, *runs)
        assert authorized == current
        assert original.comparison == current.comparison
        assert original.player_movements == current.player_movements
        assert original.fixtures == current.fixtures
        assert ast.dump(ast.parse(source).body[-1]) == ast.dump(
            ast.parse(
                (
                    repository_root / "src/dmf_pulse/private_v1/team_strength_comparison.py"
                ).read_text()
            ).body[-1]
        )  # safe success summary function unchanged
    finally:
        del sys.modules[module.__name__]
