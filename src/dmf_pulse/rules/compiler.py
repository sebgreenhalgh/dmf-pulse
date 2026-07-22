"""Validation and deterministic compilation of split-file rulesets."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from dmf_pulse import __version__
from dmf_pulse.rules.authoring import validate_and_normalize_authoring_data
from dmf_pulse.rules.canonical import canonical_rules_sha256, pretty_rules_json, self_hash
from dmf_pulse.rules.errors import RulesIntegrityError, RulesValidationError
from dmf_pulse.rules.models import (
    CompiledRuleset,
    FPLPosition,
    RulesetStatus,
    RulesetValidationReport,
    SeasonManifest,
    UnknownRule,
    VerificationStatus,
)
from dmf_pulse.rules.yaml_loader import load_rules_yaml

REQUIRED_FILES: Final = (
    "season_manifest.yaml",
    "positions.yaml",
    "scoring.yaml",
    "assists.yaml",
    "bonus.yaml",
    "squad.yaml",
    "lineup.yaml",
    "transfers.yaml",
    "prices.yaml",
    "chips.yaml",
    "deadlines.yaml",
    "special_events.yaml",
    "source_manifest.yaml",
)
SUPPORTED_EXTENSIONS: Final = {"target_2026_27_claims.yaml"}


def _safe_directory(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RulesValidationError(
            "RULESET_DIRECTORY_UNAVAILABLE", "ruleset directory is unavailable"
        ) from exc
    if not resolved.is_dir():
        raise RulesValidationError(
            "RULESET_DIRECTORY_REQUIRED", "ruleset source must be a directory"
        )
    return resolved


def _unknown_blockers(value: object, path: str) -> list[str]:
    blockers: list[str] = []
    if isinstance(value, dict):
        status = value.get("verification_status")
        if status in {VerificationStatus.UNKNOWN.value, VerificationStatus.CONFLICTED.value}:
            try:
                UnknownRule.model_validate(value)
            except ValidationError as exc:
                raise RulesValidationError(
                    "RULESET_UNKNOWN_INVALID",
                    "typed unknown values require only status, null value, and source_refs",
                ) from exc
            blockers.append(path)
            return blockers
        for key, item in value.items():
            blockers.extend(_unknown_blockers(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_unknown_blockers(item, f"{path}[{index}]"))
    return blockers


def _expect_mapping(value: dict[str, Any], key: str, filename: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise RulesValidationError(
            "RULESET_SCHEMA_INVALID", f"{filename} requires mapping field {key}"
        )
    return item


def _validate_complete_rule_shapes(data: dict[str, dict[str, Any]]) -> None:
    """Validate the scoring-facing controlled vocabulary without duplicating policy values."""

    positions = _expect_mapping(data["positions.yaml"], "positions", "positions.yaml")
    if set(positions) != {position.value for position in FPLPosition}:
        raise RulesValidationError(
            "RULESET_POSITION_INVALID", "positions must define GK, DEF, MID and FWD"
        )
    scoring = data["scoring.yaml"]
    for key in (
        "appearance",
        "goals",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "goalkeeper_saves",
        "penalties",
        "cards",
        "own_goals",
        "defensive_contributions",
    ):
        _expect_mapping(scoring, key, "scoring.yaml")
    goal_points = _expect_mapping(
        _expect_mapping(scoring, "goals", "scoring.yaml"), "points_by_position", "scoring.yaml"
    )
    if set(goal_points) != {position.value for position in FPLPosition} or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in goal_points.values()
    ):
        raise RulesValidationError(
            "RULESET_GOAL_POINTS_INVALID", "goal points require integer values for all positions"
        )
    bonus = data["bonus.yaml"]
    _expect_mapping(bonus, "bps", "bonus.yaml")
    ranks = _expect_mapping(bonus, "bonus_points_by_competition_rank", "bonus.yaml")
    if ranks != {"1": 3, "2": 2, "3": 1}:
        raise RulesValidationError(
            "RULESET_BONUS_RANK_INVALID", "bonus rank values must be 3, 2, 1"
        )
    assists = data["assists.yaml"]
    states = assists.get("classification_states")
    if states != ["DEFINITE_ASSIST", "DEFINITE_NO_ASSIST", "AMBIGUOUS_ASSIST"]:
        raise RulesValidationError(
            "RULESET_ASSIST_STATE_INVALID", "assist classification states are invalid"
        )


def _load_source(
    path: Path,
) -> tuple[SeasonManifest, dict[str, dict[str, Any]], dict[str, str], tuple[str, ...]]:
    root = _safe_directory(path)
    manifest_data = load_rules_yaml(root / "season_manifest.yaml")
    try:
        manifest = SeasonManifest.model_validate(manifest_data)
    except ValidationError as exc:
        raise RulesValidationError(
            "RULESET_MANIFEST_INVALID", "season manifest failed strict validation"
        ) from exc
    if manifest.status is RulesetStatus.ACTIVE:
        raise RulesValidationError(
            "RULESET_SOURCE_ACTIVE_PROHIBITED",
            "ACTIVE status can only be created by immutable approved publication",
        )
    expected_required = tuple(name for name in REQUIRED_FILES if name != "season_manifest.yaml")
    if tuple(manifest.required_files) != expected_required:
        raise RulesValidationError(
            "RULESET_REQUIRED_FILES", "season manifest required_files is incomplete or reordered"
        )
    if any(name not in SUPPORTED_EXTENSIONS for name in manifest.extension_files):
        raise RulesValidationError(
            "RULESET_EXTENSION_UNSUPPORTED", "season manifest lists an unsupported extension"
        )
    if any(
        candidate.is_symlink()
        for candidate in root.iterdir()
        if candidate.suffix.casefold() in {".yaml", ".yml"}
    ):
        raise RulesValidationError(
            "RULESET_FILE_SYMLINK", "symbolic-linked YAML rule files are prohibited"
        )
    expected = set(REQUIRED_FILES) | set(manifest.extension_files)
    actual = {
        candidate.name
        for candidate in root.iterdir()
        if candidate.is_file() and candidate.suffix.casefold() in {".yaml", ".yml"}
    }
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise RulesValidationError(
            "RULESET_FILE_MISSING", "required rules files are missing", blockers=tuple(missing)
        )
    if unknown:
        raise RulesValidationError(
            "RULESET_FILE_UNKNOWN", "unknown YAML files are prohibited", blockers=tuple(unknown)
        )
    data: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    for filename in sorted(expected):
        value = (
            manifest_data
            if filename == "season_manifest.yaml"
            else load_rules_yaml(root / filename)
        )
        data[filename] = value
        blockers.extend(_unknown_blockers(value, filename))
    if manifest.status is RulesetStatus.CAPTURED_UNVERIFIED:
        claims = data.get("target_2026_27_claims.yaml")
        families = claims.get("unknown_blocking_families") if isinstance(claims, dict) else None
        if (
            not isinstance(families, list)
            or not families
            or not all(isinstance(item, str) for item in families)
        ):
            raise RulesValidationError(
                "RULESET_TARGET_BLOCKERS_MISSING", "target draft must enumerate blocking families"
            )
        blockers.extend(f"target:{item}" for item in families)
    elif blockers:
        raise RulesValidationError(
            "RULESET_UNKNOWN_STATUS", "typed unknowns require a non-production draft status"
        )
    if not blockers:
        _validate_complete_rule_shapes(data)
    normalized_blockers = tuple(sorted(set(blockers)))
    data = validate_and_normalize_authoring_data(manifest, data, normalized_blockers)
    try:
        hashes = {filename: canonical_rules_sha256(value) for filename, value in data.items()}
    except ValueError as exc:
        raise RulesValidationError(
            "RULESET_CANONICAL_COLLISION", "ruleset contains colliding normalized keys"
        ) from exc
    return manifest, data, hashes, normalized_blockers


def validate_ruleset_directory(path: Path) -> RulesetValidationReport:
    manifest, data, source_hashes, blockers = _load_source(path)
    return RulesetValidationReport(
        ruleset_id=manifest.ruleset_id,
        ruleset_version=manifest.ruleset_version,
        status=manifest.status,
        production_eligible=manifest.production_eligible and not blockers,
        valid=True,
        files=tuple(sorted(data)),
        source_hashes=source_hashes,
        unknown_blockers=blockers,
        warnings=("ruleset contains unresolved required values",) if blockers else (),
    )


def compile_ruleset(path: Path) -> CompiledRuleset:
    manifest, data, source_hashes, blockers = _load_source(path)
    rules = {
        Path(name).stem: value for name, value in data.items() if name != "season_manifest.yaml"
    }
    payload: dict[str, Any] = {
        "compiler_version": __version__,
        "production_eligible": manifest.production_eligible and not blockers,
        "rules": rules,
        "ruleset_id": manifest.ruleset_id,
        "ruleset_version": manifest.ruleset_version,
        "schema_version": manifest.schema_version,
        "season_code": manifest.season_code,
        "source_bundle_sha256": canonical_rules_sha256(source_hashes),
        "source_hashes": source_hashes,
        "status": manifest.status.value,
        "unknown_blockers": list(blockers),
        "warnings": ["ruleset contains unresolved required values"] if blockers else [],
    }
    payload["ruleset_hash"] = self_hash(payload)
    return CompiledRuleset.model_validate(payload)


def ensure_compiled_ruleset_integrity(compiled: CompiledRuleset) -> None:
    """Reject in-memory mutation and inconsistent embedded source/schema metadata."""

    value = compiled.model_dump(mode="json")
    try:
        actual_hash = self_hash(value)
    except ValueError as exc:
        raise RulesIntegrityError(
            "RULESET_ARTIFACT_SCHEMA", "compiled rules contain colliding normalized keys"
        ) from exc
    if actual_hash != compiled.ruleset_hash:
        raise RulesIntegrityError(
            "RULESET_HASH_MISMATCH", "compiled ruleset self-hash does not match"
        )
    extension_files = tuple(sorted(set(compiled.source_hashes) - set(REQUIRED_FILES)))
    if any(name not in SUPPORTED_EXTENSIONS for name in extension_files):
        raise RulesIntegrityError(
            "RULESET_ARTIFACT_SCHEMA", "compiled ruleset contains unsupported source files"
        )
    expected_files = set(REQUIRED_FILES) | set(extension_files)
    if set(compiled.source_hashes) != expected_files:
        raise RulesIntegrityError(
            "RULESET_SOURCE_HASH_MISMATCH", "compiled source hash coverage is incomplete"
        )
    expected_rule_names = {Path(name).stem for name in expected_files - {"season_manifest.yaml"}}
    if set(compiled.rules) != expected_rule_names:
        raise RulesIntegrityError(
            "RULESET_ARTIFACT_SCHEMA", "compiled rules do not match source file coverage"
        )
    source_status = (
        RulesetStatus.VERIFIED if compiled.status is RulesetStatus.ACTIVE else compiled.status
    )
    manifest = SeasonManifest(
        ruleset_id=compiled.ruleset_id,
        ruleset_version=compiled.ruleset_version,
        schema_version=compiled.schema_version,
        season_code=compiled.season_code,
        status=source_status,
        production_eligible=True
        if compiled.status is RulesetStatus.ACTIVE
        else compiled.production_eligible,
        required_files=tuple(name for name in REQUIRED_FILES if name != "season_manifest.yaml"),
        extension_files=extension_files,
    )
    data: dict[str, dict[str, Any]] = {"season_manifest.yaml": manifest.model_dump(mode="json")}
    for filename in expected_files - {"season_manifest.yaml"}:
        raw_rule = compiled.rules[Path(filename).stem]
        if not isinstance(raw_rule, dict):
            raise RulesIntegrityError(
                "RULESET_ARTIFACT_SCHEMA", "compiled rule family must be a mapping"
            )
        data[filename] = raw_rule
    try:
        normalized = validate_and_normalize_authoring_data(
            manifest, data, compiled.unknown_blockers
        )
    except RulesValidationError as exc:
        raise RulesIntegrityError(
            "RULESET_ARTIFACT_SCHEMA", "compiled rules fail the authoring schema"
        ) from exc
    for filename in expected_files:
        if canonical_rules_sha256(normalized[filename]) != compiled.source_hashes[filename]:
            raise RulesIntegrityError(
                "RULESET_SOURCE_HASH_MISMATCH", "compiled rule does not match its source hash"
            )
    if canonical_rules_sha256(compiled.source_hashes) != compiled.source_bundle_sha256:
        raise RulesIntegrityError(
            "RULESET_SOURCE_HASH_MISMATCH", "compiled source bundle hash does not match"
        )


def load_compiled_ruleset(path: Path) -> CompiledRuleset:
    try:
        raw = path.read_bytes()
        if len(raw) > 10 * 1024 * 1024:
            raise RulesIntegrityError(
                "RULESET_ARTIFACT_TOO_LARGE", "compiled ruleset exceeds 10 MiB"
            )
        value = json.loads(raw.decode("utf-8"))
        compiled = CompiledRuleset.model_validate(value)
    except RulesIntegrityError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise RulesIntegrityError(
            "RULESET_ARTIFACT_INVALID", "compiled ruleset is unavailable or invalid"
        ) from exc
    ensure_compiled_ruleset_integrity(compiled)
    canonical = pretty_rules_json(compiled.model_dump(mode="json")).encode("utf-8")
    if raw != canonical:
        raise RulesIntegrityError(
            "RULESET_CANONICAL_MISMATCH", "compiled ruleset is not canonical JSON"
        )
    return compiled


def resolve_ruleset(path: Path) -> CompiledRuleset:
    return compile_ruleset(path) if path.is_dir() else load_compiled_ruleset(path)


def write_compiled_ruleset(compiled: CompiledRuleset, output: Path) -> None:
    """Atomically write canonical JSON without replacing a different artifact."""

    ensure_compiled_ruleset_integrity(compiled)
    data = pretty_rules_json(compiled.model_dump(mode="json")).encode("utf-8")
    if output.exists():
        try:
            existing = output.read_bytes()
        except OSError as exc:
            raise RulesIntegrityError(
                "RULESET_OUTPUT_UNAVAILABLE", "compiled output is unavailable"
            ) from exc
        if existing != data:
            raise RulesIntegrityError(
                "RULESET_OUTPUT_COLLISION", "compiled output already contains a different artifact"
            )
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".rules-", dir=output.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise RulesIntegrityError(
                "RULESET_OUTPUT_COLLISION", "compiled output was concurrently created"
            ) from exc
        except OSError as exc:
            raise RulesIntegrityError(
                "RULESET_OUTPUT_UNAVAILABLE", "compiled output could not be published"
            ) from exc
        temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
