"""Report executable changed-line and originating-branch coverage against R6."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path

import coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-file", required=True)
    parser.add_argument("--baseline", default="5878a39448456df0d07d58823e6dfa7c8e574715")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    measured = coverage.Coverage(data_file=args.data_file)
    measured.load()
    full_report = args.output.with_name(args.output.stem + "-full.json")
    measured.json_report(outfile=str(full_report), pretty_print=True)
    files = json.loads(full_report.read_text(encoding="utf-8"))["files"]
    diff = subprocess.run(
        ["git", "diff", "--unified=0", args.baseline, "--", "src/dmf_pulse"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    ).stdout
    changes = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            changes[current] = set()
        match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if match and current:
            start, count = int(match[1]), int(match[2] or 1)
            changes[current].update(range(start, start + count))
    reports = {}
    covered = total = 0
    for name, changed in changes.items():
        data = files.get(name) or files.get(name.replace("/", "\\"))
        if data is None:
            raise ValueError(f"changed production source has no coverage: {name}")
        executable = set(data["executed_lines"]) | set(data["missing_lines"])
        expanded = set(changed)
        statements = [
            n
            for n in ast.walk(ast.parse(Path(name).read_text(encoding="utf-8")))
            if isinstance(n, ast.stmt)
        ]
        for line in changed - executable:
            containing = [n for n in statements if n.lineno <= line <= n.end_lineno]
            if containing:
                statement = min(containing, key=lambda n: n.end_lineno - n.lineno)
                expanded.add(statement.lineno)
        relevant = expanded & executable
        missing_lines = sorted(relevant & set(data["missing_lines"]))
        arcs = {
            tuple(a)
            for key in ("executed_branches", "missing_branches")
            for a in data.get(key, [])
            if a[0] in relevant
        }
        missing_arcs = sorted(arcs & {tuple(a) for a in data.get("missing_branches", [])})
        file_total = len(relevant) + len(arcs)
        file_covered = file_total - len(missing_lines) - len(missing_arcs)
        reports[name] = {
            "covered": file_covered,
            "total": file_total,
            "missing_lines": missing_lines,
            "missing_branches": missing_arcs,
        }
        total += file_total
        covered += file_covered
    result = {
        "baseline": args.baseline,
        "covered": covered,
        "total": total,
        "percentage": 100 * covered / total,
        "files": reports,
        "scope": "Changed executable lines plus smallest containing statement origins and originating branch arcs; not the whole-repository CI threshold.",
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
