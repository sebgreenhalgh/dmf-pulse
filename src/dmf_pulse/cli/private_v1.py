"""Offline commands for the private current recommendation vertical slice."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from dmf_pulse.assurance.canonical import canonical_json_bytes
from dmf_pulse.fpl_points.errors import FplPointsError
from dmf_pulse.fpl_points.service import load_mc_policy
from dmf_pulse.ingestion.odds.current import OddsProviderCurrentInput
from dmf_pulse.ingestion.odds.mapping import CurrentFixtureMappingPlan, CurrentTeamAliasPlan
from dmf_pulse.markets.current import CurrentMarketCanonicalIdentityView
from dmf_pulse.private_v1.artifacts import (
    load_execution_input,
    load_private_input_model,
    write_synthetic_replay_bundle,
)
from dmf_pulse.private_v1.errors import PrivateV1Error
from dmf_pulse.private_v1.live import (
    PrivateLivePriorFallbackInput,
    PrivateLiveScorePriorInput,
    PrivateLiveStage7Input,
    PrivateV1LiveTransientRequest,
    PrivateV1LiveTransientService,
)
from dmf_pulse.private_v1.models import (
    PrivateCandidateActionPolicy,
    PrivateCanonicalPlayerIdentityMap,
    PrivateCurrentOwnership,
)
from dmf_pulse.private_v1.service import (
    PrivateV1RecommendationService,
    load_packaged_event_allocation_config,
)
from dmf_pulse.rules.capabilities import compile_capability_artifact
from dmf_pulse.rules.compiler import resolve_ruleset
from dmf_pulse.rules.errors import RulesError
from dmf_pulse.rules.models import RuleCapability
from dmf_pulse.rules.private_transient import (
    PrivateTransientRulesAuthority,
    seal_private_transient_rules_authority,
)

private_v1_app = typer.Typer(help="Run or replay the private current recommendation path.")


class _OutputFormat(StrEnum):
    REPORT = "report"
    JSON = "json"


def _emit_error(error: PrivateV1Error) -> None:
    typer.echo(
        json.dumps(
            {"error": {"code": error.code, "message": error.message}},
            allow_nan=False,
            sort_keys=True,
        )
    )


def _utc_timestamp(value: str, *, option: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PrivateV1Error("USAGE_INVALID", f"{option} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PrivateV1Error("USAGE_INVALID", f"{option} must include a UTC offset")
    return parsed.astimezone(UTC)


@private_v1_app.command("live-transient")
def live_transient_command(
    bootstrap: Annotated[Path, typer.Option("--bootstrap", exists=True, dir_okay=False)],
    fixtures: Annotated[Path, typer.Option("--fixtures", exists=True, dir_okay=False)],
    manager: Annotated[Path, typer.Option("--manager", exists=True, dir_okay=False)],
    ruleset_path: Annotated[Path, typer.Option("--ruleset", exists=True)],
    rules_approval_reference: Annotated[str, typer.Option("--rules-approval-reference")],
    rules_approved_at: Annotated[str, typer.Option("--rules-approved-at")],
    odds_input: Annotated[Path, typer.Option("--odds-input", exists=True, dir_okay=False)],
    team_alias_plan: Annotated[
        Path, typer.Option("--team-alias-plan", exists=True, dir_okay=False)
    ],
    fixture_mapping_plan: Annotated[
        Path, typer.Option("--fixture-mapping-plan", exists=True, dir_okay=False)
    ],
    market_identity_view: Annotated[
        Path, typer.Option("--market-identity-view", exists=True, dir_okay=False)
    ],
    player_identity_map: Annotated[
        Path, typer.Option("--player-identity-map", exists=True, dir_okay=False)
    ],
    score_priors: Annotated[Path, typer.Option("--score-priors", exists=True, dir_okay=False)],
    stage7: Annotated[Path, typer.Option("--stage7", exists=True, dir_okay=False)],
    ownership: Annotated[Path, typer.Option("--ownership", exists=True, dir_okay=False)],
    candidate_policy: Annotated[
        Path, typer.Option("--candidate-policy", exists=True, dir_okay=False)
    ],
    mc_policy: Annotated[Path, typer.Option("--mc-policy", exists=True, dir_okay=False)],
    gameweek: Annotated[int, typer.Option("--gameweek", min=1)],
    captured_at: Annotated[str, typer.Option("--captured-at")],
    information_cutoff: Annotated[str, typer.Option("--information-cutoff")],
    mapping_decided_at: Annotated[str, typer.Option("--mapping-decided-at")],
    run_id: Annotated[str, typer.Option("--run-id")],
    code_sha: Annotated[str, typer.Option("--code-sha")],
    root_seed: Annotated[int, typer.Option("--root-seed", min=0)],
    scenario_count: Annotated[int, typer.Option("--scenario-count", min=1)],
    prior_fallbacks: Annotated[
        Path | None,
        typer.Option("--prior-fallbacks", exists=True, dir_okay=False),
    ] = None,
) -> None:
    """Display one real private recommendation; never create a replay or output artifact."""

    try:
        ruleset = resolve_ruleset(ruleset_path)
        capability = compile_capability_artifact(ruleset, RuleCapability.FULL_SEASON)
        authority = seal_private_transient_rules_authority(
            PrivateTransientRulesAuthority.model_construct(
                ruleset_id=ruleset.ruleset_id,
                ruleset_version=ruleset.ruleset_version,
                ruleset_sha256=ruleset.ruleset_hash,
                capability_sha256=capability.capability_hash,
                operator_approval_reference=rules_approval_reference,
                operator_approved_at=_utc_timestamp(
                    rules_approved_at, option="--rules-approved-at"
                ),
                attestation_sha256="0" * 64,
            )
        )
        odds = load_private_input_model(odds_input, OddsProviderCurrentInput)
        aliases = load_private_input_model(
            team_alias_plan, CurrentTeamAliasPlan, maximum_bytes=4 * 1024 * 1024
        )
        fixture_plan = load_private_input_model(
            fixture_mapping_plan, CurrentFixtureMappingPlan, maximum_bytes=4 * 1024 * 1024
        )
        market_view = load_private_input_model(
            market_identity_view,
            CurrentMarketCanonicalIdentityView,
            maximum_bytes=4 * 1024 * 1024,
        )
        player_map = load_private_input_model(
            player_identity_map,
            PrivateCanonicalPlayerIdentityMap,
            maximum_bytes=16 * 1024 * 1024,
        )
        prior_set = load_private_input_model(score_priors, PrivateLiveScorePriorInput)
        minutes_set = load_private_input_model(stage7, PrivateLiveStage7Input)
        ownership_input = load_private_input_model(
            ownership, PrivateCurrentOwnership, maximum_bytes=4 * 1024 * 1024
        )
        candidates = load_private_input_model(
            candidate_policy, PrivateCandidateActionPolicy, maximum_bytes=1024 * 1024
        )
        fallback_input = (
            load_private_input_model(
                prior_fallbacks,
                PrivateLivePriorFallbackInput,
                maximum_bytes=4 * 1024 * 1024,
            )
            if prior_fallbacks is not None
            else None
        )
        request = PrivateV1LiveTransientRequest(
            run_id=run_id,
            code_sha=code_sha,
            bootstrap_path=bootstrap,
            fixtures_path=fixtures,
            manager_declaration_path=manager,
            target_gameweek=gameweek,
            captured_at=_utc_timestamp(captured_at, option="--captured-at"),
            information_cutoff=_utc_timestamp(information_cutoff, option="--information-cutoff"),
            ruleset=ruleset,
            full_season_capability=capability,
            private_rules_authority=authority,
            odds_input=odds,
            team_alias_plan=aliases,
            fixture_mapping_plan=fixture_plan,
            mapping_decided_at=_utc_timestamp(mapping_decided_at, option="--mapping-decided-at"),
            market_identity_view=market_view,
            player_identity_map=player_map,
            score_priors=prior_set.score_priors,
            manual_minutes=minutes_set.fixtures,
            ownership=ownership_input,
            candidate_action_policy=candidates,
            prior_fallbacks=fallback_input,
            root_seed=root_seed,
            scenario_count=scenario_count,
            stage9_monte_carlo_policy=load_mc_policy(mc_policy),
            event_allocation_config=load_packaged_event_allocation_config(),
        )
        result = PrivateV1LiveTransientService().run(request)
        typer.echo(result.report, nl=False)
        del result
    except PrivateV1Error as exc:
        _emit_error(exc)
        raise typer.Exit(2) from None
    except (FplPointsError, RulesError) as exc:
        _emit_error(PrivateV1Error(exc.code, exc.message))
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError, OSError):
        _emit_error(
            PrivateV1Error("LIVE_TRANSIENT_FAILED", "live transient execution failed safely")
        )
        raise typer.Exit(2) from None


@private_v1_app.command("run")
def run_command(
    input_path: Annotated[
        Path,
        typer.Option(
            "--input",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Strict private-v1-execution-input-v1 JSON.",
        ),
    ],
    freeze_dir: Annotated[
        Path | None,
        typer.Option(
            "--freeze-dir",
            file_okay=False,
            help="New directory for a retention-authorised synthetic replay bundle.",
        ),
    ] = None,
    output_format: Annotated[
        _OutputFormat,
        typer.Option(
            "--output",
            help="Emit the human report or the canonical machine-readable decision JSON.",
        ),
    ] = _OutputFormat.REPORT,
) -> None:
    """Execute the in-memory path; optionally freeze a synthetic-only replay bundle."""

    try:
        execution = load_execution_input(input_path)
        if freeze_dir is not None and execution.retention_class != "SYNTHETIC_REPLAY_ALLOWED":
            raise PrivateV1Error(
                "REPLAY_RETENTION_FORBIDDEN",
                "current source rights do not permit a persistent replay bundle",
            )
        result = PrivateV1RecommendationService().run(execution)
        if freeze_dir is not None:
            manifest = write_synthetic_replay_bundle(
                execution,
                result.decision,
                result.report,
                freeze_dir,
            )
        else:
            manifest = None
        if output_format is _OutputFormat.JSON:
            typer.echo(canonical_json_bytes(result.decision).decode("utf-8"), nl=False)
        else:
            typer.echo(result.report, nl=False)
            if manifest is not None:
                typer.echo(f"Replay manifest: {manifest.manifest_sha256}")
                typer.echo(f"Replay: dmf private-v1 replay --bundle {freeze_dir}")
    except PrivateV1Error as exc:
        _emit_error(exc)
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError):
        _emit_error(PrivateV1Error("PRIVATE_V1_FAILED", "private recommendation execution failed"))
        raise typer.Exit(2) from None


@private_v1_app.command("replay")
def replay_command(
    bundle: Annotated[
        Path,
        typer.Option(
            "--bundle",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Frozen synthetic replay bundle directory.",
        ),
    ],
    output_format: Annotated[
        _OutputFormat,
        typer.Option(
            "--output",
            help="Emit the human report or the canonical machine-readable decision JSON.",
        ),
    ] = _OutputFormat.REPORT,
) -> None:
    """Verify and recompute a synthetic replay bundle entirely offline."""

    try:
        replay = PrivateV1RecommendationService().replay(bundle)
        if output_format is _OutputFormat.JSON:
            typer.echo(canonical_json_bytes(replay.run.decision).decode("utf-8"), nl=False)
        else:
            typer.echo(replay.run.report, nl=False)
            typer.echo(f"Replay verified: {replay.manifest_sha256}")
    except PrivateV1Error as exc:
        _emit_error(exc)
        raise typer.Exit(2) from None
    except (ValidationError, ValueError, ArithmeticError):
        _emit_error(PrivateV1Error("REPLAY_FAILED", "private replay execution failed"))
        raise typer.Exit(2) from None


__all__ = ["private_v1_app"]
