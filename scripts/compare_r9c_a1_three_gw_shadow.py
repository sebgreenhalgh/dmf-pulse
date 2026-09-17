"""Print the offline synthetic R9C-A1.03 four-world decision comparison.

This is a repository test/review probe, not an operator command.  It has no
arguments, makes no network request, does not access credentials, and writes
no result file.  It stops after the canonical three-GW comparison.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    # This is explicitly a repository review probe; production packaging never
    # imports test support or exposes this construction path.
    sys.path.insert(0, str(repository_root))
    from dmf_pulse.private_v1.shadow_comparison import run_four_world_shadow_comparison
    from tests.unit.private_v1.a1_03_support import build_a1_03_inputs

    with tempfile.TemporaryDirectory(prefix="dmf-r9c-a1-03-") as temporary:
        execution, shadow = build_a1_03_inputs(repository_root, Path(temporary))
        comparison = run_four_world_shadow_comparison(execution, shadow)
    print(json.dumps(asdict(comparison), sort_keys=True, default=str))


if __name__ == "__main__":
    main()
