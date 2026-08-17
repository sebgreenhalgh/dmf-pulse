"""Supplemental offline static assurance for Stage 12.

This does not replace repository Ruff or mypy; it catches high-risk omissions when those tools are
unavailable in a restricted implementation workspace.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (
    *sorted((ROOT / "src/dmf_pulse/evaluation").glob("*.py")),
    ROOT / "src/dmf_pulse/cli/evaluate.py",
)
FORBIDDEN_IMPORTS = {"requests", "httpx", "socket", "urllib.request"}
FORBIDDEN_TOKENS = ("NotImplementedError", "TODO")


def main() -> None:
    errors: list[str] = []
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        if not text.endswith("\n"):
            errors.append(f"NO_FINAL_NEWLINE:{path}")
        for number, line in enumerate(text.splitlines(), 1):
            if line.rstrip() != line:
                errors.append(f"TRAILING_WHITESPACE:{path}:{number}")
            for token in FORBIDDEN_TOKENS:
                if token in line:
                    errors.append(f"FORBIDDEN_TOKEN:{token}:{path}:{number}")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    if any(
                        name == item or name.startswith(item + ".") for item in FORBIDDEN_IMPORTS
                    ):
                        errors.append(f"NETWORK_IMPORT:{name}:{path}:{node.lineno}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                public = not node.name.startswith("_")
                if public and node.returns is None:
                    errors.append(f"MISSING_RETURN_ANNOTATION:{path}:{node.lineno}:{node.name}")
                args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                for arg in args:
                    if arg.arg in {"self", "cls"}:
                        continue
                    if public and arg.annotation is None:
                        errors.append(
                            f"MISSING_ARG_ANNOTATION:{path}:{node.lineno}:{node.name}:{arg.arg}"
                        )
                for default in [*node.args.defaults, *node.args.kw_defaults]:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        errors.append(f"MUTABLE_DEFAULT:{path}:{node.lineno}:{node.name}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS files={len(TARGETS)}")


if __name__ == "__main__":
    main()
