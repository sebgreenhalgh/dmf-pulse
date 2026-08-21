"""Build the private GW1 penalty overlay and safe three-world review artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from dmf_pulse.assurance.canonical import pretty_json, sha256_file
from dmf_pulse.availability.current import current_team_id
from dmf_pulse.ingestion.fpl.current import CurrentFplInputRequest, CurrentFplInputService
from dmf_pulse.player_evidence.catalogue import build_current_player_history_catalogue
from dmf_pulse.player_evidence.models import (
    HistorySensitivityWorld,
    PlayerPosteriorArtifact,
    PriceWorld,
    candidate_price_policy,
)
from dmf_pulse.player_evidence.overlays import (
    compile_current_allocation_overlay,
    load_private_overlay_review,
)
from dmf_pulse.player_evidence.role_priors import (
    load_role_prior_candidate,
    role_priors_from_candidate,
)

CATALOGUE_SHA256 = "9d655a2dc8e60eca0898f4bc04e8caf7b264887af1d62bfe61c5288cbdd75f11"
ROLE_PRIOR_SHA256 = "007e4d400d8f72eccc50541a9e9b385042bd3eb5d724b0b1d76e7cc69f42afb8"
POSTERIOR_SHA256S = {
    HistorySensitivityWorld.CENTRAL_TEMPORARY: (
        "537b2ab3c19aba381e6020972cd037b3f62665309c423037049020f0d4f0239f"
    ),
    HistorySensitivityWorld.LOW_SHRINKAGE: (
        "2bba62e765c83ba0ed114e78d168311e1f33aa144143b121703af2e5acfedbec"
    ),
    HistorySensitivityWorld.HIGH_SHRINKAGE: (
        "b876b34d8669cf0acbaaa1a8136e90058573b4292c6dc016b7bf59e52992595e"
    ),
}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _regular_non_symlink(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _write_new(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(pretty_json(value))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--information-cutoff", required=True)
    parser.add_argument("--private-review", type=Path, required=True)
    parser.add_argument("--role-prior", type=Path, required=True)
    parser.add_argument("--central-posterior", type=Path, required=True)
    parser.add_argument("--low-posterior", type=Path, required=True)
    parser.add_argument("--high-posterior", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    inputs = (
        arguments.bootstrap,
        arguments.fixtures,
        arguments.private_review,
        arguments.role_prior,
        arguments.central_posterior,
        arguments.low_posterior,
        arguments.high_posterior,
    )
    if not all(_regular_non_symlink(path) for path in inputs):
        raise SystemExit("all inputs must be regular non-symlink files")
    output_directory = arguments.output_directory
    if (
        not output_directory.is_dir()
        or output_directory.is_symlink()
        or any(output_directory.iterdir())
    ):
        raise SystemExit("output directory must exist, be regular, and be initially empty")
    cutoff = _utc(arguments.information_cutoff)
    captured_at = _utc(arguments.captured_at)
    produced_at = datetime.now(UTC)
    if produced_at > cutoff:
        raise SystemExit("overlay compilation is after the approved information cutoff")

    bundle = CurrentFplInputService().compile(
        CurrentFplInputRequest(
            bootstrap_path=arguments.bootstrap,
            fixtures_path=arguments.fixtures,
            competition_key="PL",
            season_code="2026/27",
            captured_at=captured_at,
            information_cutoff=cutoff,
            rights_profile_id="fpl_official_private_manual_v1",
            gameweek=1,
        )
    )
    if bundle.target_event.deadline_at != cutoff:
        raise SystemExit("manual current-FPL bundle has the wrong GW1 deadline")
    team_ids_by_provider = {team.provider_team_id: current_team_id(team) for team in bundle.teams}
    catalogue = build_current_player_history_catalogue(bundle, stage7_team_ids=team_ids_by_provider)
    if (
        catalogue.semantic_sha256 != CATALOGUE_SHA256
        or len(catalogue.players) != 599
        or len(bundle.teams) != 20
    ):
        raise SystemExit("manual inputs do not reproduce the approved current catalogue")

    review = load_private_overlay_review(arguments.private_review)
    role_prior = load_role_prior_candidate(arguments.role_prior)
    if role_prior.artifact_sha256 != ROLE_PRIOR_SHA256:
        raise SystemExit("role-prior artifact is not the accepted GW1 candidate")
    posterior_paths = {
        HistorySensitivityWorld.CENTRAL_TEMPORARY: arguments.central_posterior,
        HistorySensitivityWorld.LOW_SHRINKAGE: arguments.low_posterior,
        HistorySensitivityWorld.HIGH_SHRINKAGE: arguments.high_posterior,
    }
    posteriors = {
        world: PlayerPosteriorArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        for world, path in posterior_paths.items()
    }
    for world, posterior in posteriors.items():
        if posterior.artifact_sha256 != POSTERIOR_SHA256S[world]:
            raise SystemExit(f"{world.value} posterior hash does not match the accepted artifact")

    compiled = compile_current_allocation_overlay(
        review=review,
        catalogue=catalogue,
        team_ids_by_provider=team_ids_by_provider,
        posteriors=posteriors,
        role_priors=role_priors_from_candidate(role_prior),
        price_policy=candidate_price_policy(PriceWorld.PRICE_OFF),
        produced_at=produced_at,
    )
    output_paths = {
        HistorySensitivityWorld.CENTRAL_TEMPORARY: output_directory / "central-allocation.json",
        HistorySensitivityWorld.LOW_SHRINKAGE: output_directory / "low-allocation.json",
        HistorySensitivityWorld.HIGH_SHRINKAGE: output_directory / "high-allocation.json",
    }
    receipt_path = output_directory / "penalty-overlay-receipt.json"
    sensitivity_path = output_directory / "allocation-sensitivity-summary.json"
    private_compiled_path = output_directory / "private-compiled-review.json"
    for world, path in output_paths.items():
        _write_new(path, compiled.allocations[world])
    _write_new(receipt_path, compiled.receipt)
    _write_new(sensitivity_path, compiled.sensitivity_summary)

    player_by_id = {player.player_id: player for player in catalogue.players}
    source_by_id = {player.provider_element_id: player for player in bundle.players}
    materially_unstable = sorted(
        (
            row
            for row in compiled.sensitivity_rows
            if row.maximum_absolute_goal_share_movement
            >= compiled.sensitivity_summary.goal_share.material_threshold
            or row.maximum_absolute_assist_share_movement
            >= compiled.sensitivity_summary.assist_share.material_threshold
        ),
        key=lambda row: max(
            row.maximum_absolute_goal_share_movement,
            row.maximum_absolute_assist_share_movement,
        ),
        reverse=True,
    )
    private_payload = {
        "schema_version": "gw1-player-allocation-overlay-private-compiled-review-v1",
        "status": "PRIVATE_OPERATOR_REVIEW_NOT_FOR_PUBLICATION",
        "private_review": review.model_dump(mode="json"),
        "penalty_assignment_artifact_sha256": compiled.assignment_artifact_sha256,
        "assignments": [assignment.model_dump(mode="json") for assignment in compiled.assignments],
        "role_override_artifact_sha256": compiled.role_override_artifact_sha256,
        "sensitivity_rows": [row.model_dump(mode="json") for row in compiled.sensitivity_rows],
        "largest_materially_unstable_players": [
            {
                **row.model_dump(mode="json"),
                "display_name": source_by_id[player_by_id[row.player_id].source_player_id].web_name,
            }
            for row in materially_unstable[:25]
        ],
        "raw_fpl_history_persisted": False,
        "current_fpl_catalogue_persisted": False,
    }
    _write_new(private_compiled_path, private_payload)

    safe_summary = {
        "schema_version": "gw1-player-allocation-overlay-command-summary-v1",
        "catalogue_semantic_sha256": catalogue.semantic_sha256,
        "player_count": len(catalogue.players),
        "team_count": len(bundle.teams),
        "penalty_assignment_artifact_sha256": compiled.assignment_artifact_sha256,
        "penalty_assignment_count": len(compiled.assignments),
        "classification_counts": compiled.receipt.classification_counts,
        "role_override_count": len(review.role_overrides),
        "central_allocation_sha256": compiled.allocations[
            HistorySensitivityWorld.CENTRAL_TEMPORARY
        ].artifact_sha256,
        "low_allocation_sha256": compiled.allocations[
            HistorySensitivityWorld.LOW_SHRINKAGE
        ].artifact_sha256,
        "high_allocation_sha256": compiled.allocations[
            HistorySensitivityWorld.HIGH_SHRINKAGE
        ].artifact_sha256,
        "sensitivity_artifact_sha256": compiled.sensitivity_summary.artifact_sha256,
        "receipt_sha256": compiled.receipt.receipt_sha256,
        "output_file_sha256s": {
            path.name: sha256_file(path)
            for path in (*output_paths.values(), receipt_path, sensitivity_path)
        },
        "raw_fpl_history_persisted": False,
        "current_fpl_catalogue_persisted": False,
        "history_network_request_count": 0,
        "player_allocation_human_accepted": False,
    }
    del bundle
    del catalogue
    print(json.dumps(safe_summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
