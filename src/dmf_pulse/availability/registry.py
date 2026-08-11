"""Pure semantic identities for the MIN-007F availability registry."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

_DATASET_FIELDS = (
    "schema_version",
    "dataset_key",
    "competition_code",
    "season_code",
    "training_cutoff",
    "dataset_sha256",
    "policy_sha256",
    "training_example_count",
)
_MODEL_FIELDS = (
    "schema_version",
    "model_key",
    "dataset_version_sha256",
    "role_artifact_sha256",
    "minute_artifact_sha256",
    "policy_sha256",
    "model_family",
    "code_identity",
)
_PREDICTION_FIELDS = (
    "schema_version",
    "fixture_id",
    "team_id",
    "as_of",
    "feature_cutoff",
    "model_version_sha256",
    "dataset_version_sha256",
    "policy_sha256",
    "source_dependencies",
    "hard_eligibility",
    "manager_context",
    "manager_regime_id",
    "seed",
    "sample_count",
    "bench_size",
    "bench_goalkeeper_slots",
    "code_identity",
)

_DEPENDENCY_FIELDS = ("dependency_type", "dependency_key", "semantic_sha256")
_ELIGIBILITY_FIELDS = ("player_id", "reason", "hard_ineligible")
_MANAGER_CONTEXT_FIELDS = (
    "manager_regime_id",
    "current_manager_team_lineups",
    "new_manager",
    "promoted_team",
    "target_league_team_lineups",
)


def _typed_fields(value: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Retain only the explicitly semantic fields of a registry contract."""

    return {field: value[field] for field in fields if field in value}


def _normalise_prediction(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _typed_fields(value, _PREDICTION_FIELDS)
    dependencies = result.get("source_dependencies")
    if isinstance(dependencies, list):
        result["source_dependencies"] = [
            _typed_fields(item, _DEPENDENCY_FIELDS) if isinstance(item, Mapping) else item
            for item in dependencies
        ]
    eligibility = result.get("hard_eligibility")
    if isinstance(eligibility, list):
        result["hard_eligibility"] = [
            _typed_fields(item, _ELIGIBILITY_FIELDS) if isinstance(item, Mapping) else item
            for item in eligibility
        ]
    context = result.get("manager_context")
    if isinstance(context, Mapping):
        result["manager_context"] = _typed_fields(context, _MANAGER_CONTEXT_FIELDS)
    return result


def canonical_semantic_sha256(value: object) -> str:
    """Hash one canonical JSON semantic value without runtime metadata."""

    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("semantic identity must be finite, UTF-8 JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def dataset_version_semantic_sha256(value: Mapping[str, Any]) -> str:
    """Return the content identity of a dataset-version declaration."""

    return canonical_semantic_sha256(_typed_fields(value, _DATASET_FIELDS))


def model_version_semantic_sha256(value: Mapping[str, Any]) -> str:
    """Return the content identity of a model-version declaration."""

    return canonical_semantic_sha256(_typed_fields(value, _MODEL_FIELDS))


def prediction_input_signature_sha256(value: Mapping[str, Any]) -> str:
    """Return a stable identity for a complete, cutoff-safe prediction input."""
    return canonical_semantic_sha256(_normalise_prediction(value))
