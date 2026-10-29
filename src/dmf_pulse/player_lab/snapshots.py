"""Freeze already computed Stage-9 output without recomputing a projection."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from importlib.resources import files

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.fpl_points.models import GameweekPlayerProjectionSummary
from dmf_pulse.ingestion.models import RightsCapability
from dmf_pulse.player_lab.contracts import PlayerForecast, PlayerKey, SourceRef, seal
from dmf_pulse.player_lab.rights import require_sources


def decimal_pmf(values: dict[int, float]) -> dict[int, Decimal]:
    """Deterministic float-to-Decimal mass normalization, recorded in v1 policy.

    Stage 9 accepts 1e-10 mass error; Stage 12 requires exact Decimal unit mass.
    Keep the source mean unchanged; do not call this conversion a new forecast.
    """
    with localcontext() as context:
        context.prec = 28
        raw = {key: Decimal(str(value)) for key, value in sorted(values.items())}
        total = sum(raw.values(), Decimal(0))
        if (
            not raw
            or not total.is_finite()
            or abs(total - 1) > Decimal("1e-10")
            or any(value < 0 for value in raw.values())
        ):
            raise ValueError("Stage-9 PMF invalid")
        result = {
            key: (value / total).quantize(Decimal("0.000000000000000001"), rounding=ROUND_HALF_EVEN)
            for key, value in raw.items()
        }
        if any(raw[key] > 0 and value == 0 for key, value in result.items()):
            raise ValueError("positive PMF support is below the declared 18-decimal representation")
        largest = max(result, key=lambda key: result[key])
        result[largest] += 1 - sum(result.values(), Decimal(0))
        return result


def snapshot_projection(
    summary: GameweekPlayerProjectionSummary,
    *,
    key: PlayerKey,
    generated_at: datetime,
    information_cutoff: datetime,
    deadline_at: datetime,
    label_finality_cutoff: datetime,
    sources: tuple[SourceRef, ...],
    input_sha256: str,
    code_sha: str,
    position: str,
    expected_minutes: Decimal | None,
) -> PlayerForecast:
    """Current registry admits synthetic evidence only; real private snapshots deny."""
    require_sources(sources, RightsCapability.DERIVED_STORAGE)
    summary_sha = canonical_sha256(summary.model_dump(mode="json"))
    registry = json.loads(
        files("dmf_pulse.player_lab.resources")
        .joinpath("source-registry.json")
        .read_text(encoding="utf-8")
    )
    matches = [
        record.get("qualified_projections", {}).get(summary_sha)
        for source in sources
        if (record := registry["sources"].get(source.source_id)) is not None
    ]
    if not any(
        item is not None
        and item.get("key") == key.model_dump(mode="json")
        and item.get("input_sha256") == input_sha256
        for item in matches
    ):
        raise ValueError("projection summary/input not qualified for synthetic retention")
    if str(key.player_id) != summary.player_id:
        raise ValueError("projection/player identity differs")
    return seal(
        PlayerForecast.model_construct(
            key=key,
            dataset_mode="SYNTHETIC",
            model_id="PULSE_CURRENT_REGISTERED_CHAMPION",
            model_version_ids=tuple(sorted(summary.model_version_ids)),
            code_sha=code_sha,
            ruleset_sha256=summary.ruleset_hash,
            source_summary_sha256=summary_sha,
            input_sha256=input_sha256,
            mean=Decimal(str(summary.expected_points)),
            pmf=decimal_pmf(summary.pmf),
            components={
                name: Decimal(str(item.expected_points))
                for name, item in summary.component_breakdown.items()
            },
            expected_minutes=expected_minutes,
            position=position,
            generated_at=generated_at,
            information_cutoff=information_cutoff,
            deadline_at=deadline_at,
            label_finality_cutoff=label_finality_cutoff,
            sources=sources,
            semantic_sha256="0" * 64,
        )
    )
