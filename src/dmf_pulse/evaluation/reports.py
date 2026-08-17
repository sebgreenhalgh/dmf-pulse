"""Separated machine-readable and human-readable evaluation scorecards."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from dmf_pulse.evaluation.artifacts import persist_artifact, seal
from dmf_pulse.evaluation.models import (
    EvaluationLineage,
    EvaluationReport,
    ScorecardRow,
)


def _markdown_cell(value: object) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def build_report(
    *,
    report_id: str,
    rows: tuple[ScorecardRow, ...],
    lineage: EvaluationLineage,
    limitations: tuple[str, ...] = (),
) -> EvaluationReport:
    if not rows:
        raise ValueError("evaluation report requires at least one scorecard row")
    if len(rows) != len(set(rows)):
        raise ValueError("evaluation report rows must be unique")
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                item.layer,
                item.metric_family.value,
                item.dataset_mode.value,
                item.forecast_origin,
                item.horizon,
                item.subgroup,
                item.benchmark_id,
                item.metric_name,
            ),
        )
    )
    modes = tuple(sorted({item.dataset_mode for item in ordered}, key=lambda item: item.value))
    counts = Counter(item.layer for item in ordered)
    value = EvaluationReport(
        report_id=report_id,
        rows=ordered,
        dataset_modes=modes,
        headline_mode=modes[0] if len(modes) == 1 else None,
        forecast_rows=counts["FORECAST"],
        distribution_rows=counts["DISTRIBUTION"],
        decision_rows=counts["DECISION"],
        operational_rows=counts["OPERATIONAL"],
        limitations=tuple(sorted(set(limitations))),
        lineage=lineage,
        report_sha256="0" * 64,
    )
    return seal(value, "report_sha256")


def render_markdown(report: EvaluationReport) -> str:
    lines = [
        f"# Evaluation report {_markdown_cell(report.report_id)}",
        "",
        f"- Report hash: `{report.report_sha256}`",
        f"- Dataset modes: {', '.join(item.value for item in report.dataset_modes)}",
        f"- Headline mode: {report.headline_mode.value if report.headline_mode else 'NONE — MODES SEPARATED'}",
        "",
    ]
    for layer in ("FORECAST", "DISTRIBUTION", "DECISION", "OPERATIONAL"):
        lines.extend(
            [
                f"## {layer.title()}",
                "",
                "| Mode | Origin | Horizon | Subgroup | Benchmark | Metric family | Metric | Value | Status | Limitations |",
                "|---|---|---:|---|---|---|---|---:|---|---|",
            ]
        )
        for row in report.rows:
            if row.layer != layer:
                continue
            value = "—" if row.metric_value is None else str(row.metric_value)
            row_limitations = _markdown_cell(", ".join(row.limitations)) or "NONE"
            lines.append(
                f"| {row.dataset_mode.value} | {row.forecast_origin.isoformat()} | "
                f"{row.horizon} | {_markdown_cell(row.subgroup)} | "
                f"{_markdown_cell(row.benchmark_id)} | {row.metric_family.value} | "
                f"{_markdown_cell(row.metric_name)} | "
                f"{value} | {_markdown_cell(row.status)} | {row_limitations} |"
            )
        lines.append("")
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {_markdown_cell(item)}" for item in report.limitations)
    lines.append("")
    return "\n".join(lines)


def persist_report(
    report: EvaluationReport,
    *,
    artifact_root: Path,
) -> tuple[Path, Path]:
    json_path = persist_artifact(
        report,
        artifact_root=artifact_root,
        category="reports",
        identity=report.report_id,
    )
    markdown_path = json_path.with_suffix(".md")
    markdown = render_markdown(report).encode("utf-8")
    if markdown_path.exists() and markdown_path.read_bytes() != markdown:
        raise ValueError("immutable report markdown path already differs")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    if not markdown_path.exists():
        markdown_path.write_bytes(markdown)
    return json_path, markdown_path
