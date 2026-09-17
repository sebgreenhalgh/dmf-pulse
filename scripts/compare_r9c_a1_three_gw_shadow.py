"""Generate offline synthetic R9C-A1.03 four-world decision evidence.

This is a repository test/review probe, not an operator command.  It has no
provider request, does not access credentials, and writes only when an explicit
output path is supplied. It stops after the canonical three-GW comparison.
"""

from __future__ import annotations

import json
import sys
import tempfile
from argparse import ArgumentParser
from pathlib import Path


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--case",
        choices=("root", "continuation"),
        default="root",
    )
    parser.add_argument("--generating-implementation-sha", required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    # This is explicitly a repository review probe; production packaging never
    # imports test support or exposes this construction path.
    sys.path.insert(0, str(repository_root))
    from dmf_pulse.private_v1.shadow_comparison import (
        build_shadow_comparison_artifact,
        run_four_world_shadow_comparison,
    )
    from tests.unit.private_v1.a1_03_support import build_a1_03_inputs

    with tempfile.TemporaryDirectory(prefix="dmf-r9c-a1-03-") as temporary:
        execution, shadow = build_a1_03_inputs(
            repository_root,
            Path(temporary),
            candidate_saves_per_gameweek=1000 if arguments.case == "root" else 40,
            force_candidate_low_current_minutes=arguments.case == "continuation",
        )
        comparison = run_four_world_shadow_comparison(execution, shadow)
    artifact = build_shadow_comparison_artifact(
        comparison,
        generating_implementation_sha=arguments.generating_implementation_sha,
        case="ROOT_SENSITIVE" if arguments.case == "root" else "CONTINUATION_SENSITIVE",
    )
    body = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(body, end="")
    else:
        arguments.output.write_text(body, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
