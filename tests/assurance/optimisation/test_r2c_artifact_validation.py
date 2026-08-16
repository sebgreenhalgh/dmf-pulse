"""Adversarial R2C checks for immutable OPT-010 result artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

import dmf_pulse.optimisation.artifacts as artifacts
from dmf_pulse.fpl_points.artifacts import canonical_json_bytes, semantic_sha256, sha256_bytes
from dmf_pulse.fpl_points.models import GameweekProjectionResult
from dmf_pulse.optimisation.artifacts import load_verified_artifact, persist_result
from dmf_pulse.optimisation.errors import OptimisationError
from dmf_pulse.optimisation.models import (
    CandidatePoolSnapshot,
    OneGameweekOptimisationRequest,
    OneGameweekOptimisationResult,
)
from dmf_pulse.optimisation.service import optimise_one_gameweek
from dmf_pulse.optimisation.validation import validate_result_against_request
from tests.support.optimisation_factories import projection, request, synthetic_ruleset


def _rehash[ArtifactModel: BaseModel](value: ArtifactModel, field: str) -> ArtifactModel:
    payload = value.model_dump(mode="json")
    payload[field] = None
    return value.model_copy(update={field: semantic_sha256(payload)})


def _success_result() -> tuple[
    OneGameweekOptimisationRequest,
    GameweekProjectionResult,
    OneGameweekOptimisationResult,
]:
    rules = synthetic_ruleset()
    req = request()
    stage9 = projection(rules.ruleset_hash)
    result = optimise_one_gameweek(req, stage9, rules)
    assert result.status == "SUCCESS"
    return req, stage9, result


def test_result_artifact_requires_exact_canonical_detached_and_embedded_hashes(
    tmp_path: Path,
) -> None:
    _, _, result = _success_result()
    artifact = persist_result(
        result,
        artifact_root=tmp_path,
        gameweek_id=result.gameweek_id,
        request_id=result.request_id,
    )
    assert load_verified_artifact(artifact, OneGameweekOptimisationResult) == result

    artifact.with_suffix(".sha256").write_bytes(b"0" * 64 + b"  result.json\n")
    with pytest.raises(OptimisationError, match="detached hash"):
        load_verified_artifact(artifact, OneGameweekOptimisationResult)

    artifact.write_bytes(
        canonical_json_bytes(result.model_copy(update={"result_sha256": "0" * 64}))
    )
    artifact.with_suffix(".sha256").write_bytes(
        f"{sha256_bytes(artifact.read_bytes())}  {artifact.name}\n".encode("ascii")
    )
    with pytest.raises(OptimisationError, match="semantic payload"):
        load_verified_artifact(artifact, OneGameweekOptimisationResult)


def test_validate_result_recomputes_plan_evaluation_and_lineage(tmp_path: Path) -> None:
    req, stage9, result = _success_result()
    rules = synthetic_ruleset()
    assert result.recommended_plan is not None
    altered_distribution = result.recommended_plan.distribution.model_copy(
        update={"median": result.recommended_plan.distribution.median + 1}
    )
    altered_plan = _rehash(
        result.recommended_plan.model_copy(
            update={"point_distribution": altered_distribution, "plan_sha256": "0" * 64}
        ),
        "plan_sha256",
    )
    altered_result = result.model_copy(
        update={
            "recommended_plan": altered_plan,
            "tied_optimal_plans": (altered_plan,),
            "result_sha256": "0" * 64,
        }
    )
    altered_result = _rehash(altered_result, "result_sha256")
    artifact = persist_result(
        altered_result,
        artifact_root=tmp_path,
        gameweek_id=altered_result.gameweek_id,
        request_id=altered_result.request_id,
    )
    loaded = load_verified_artifact(artifact, OneGameweekOptimisationResult)
    report = validate_result_against_request(req, stage9, rules, loaded)
    assert not report.legal
    assert {issue.code for issue in report.issues} == {
        "PLAN_EVALUATION_MISMATCH",
        "RESULT_RECOMPUTATION_MISMATCH",
    }


def test_result_artifact_path_is_confined_and_immutable(tmp_path: Path) -> None:
    _, _, result = _success_result()
    for unsafe in ("..", "GW/1", "GW\\1", "C:GW"):
        with pytest.raises(OptimisationError, match="safe artifact path segment"):
            persist_result(
                result,
                artifact_root=tmp_path,
                gameweek_id=unsafe,
                request_id=result.request_id,
            )
    artifact = persist_result(
        result,
        artifact_root=tmp_path,
        gameweek_id=result.gameweek_id,
        request_id=result.request_id,
    )
    artifact.write_bytes(b"immutable collision")
    with pytest.raises(OptimisationError, match="immutable artifact collision"):
        persist_result(
            result,
            artifact_root=tmp_path,
            gameweek_id=result.gameweek_id,
            request_id=result.request_id,
        )


def test_artifact_helpers_fail_closed_for_hashless_and_concurrent_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A model without an embedded digest remains a valid generic write, while immutable result
    # loading requires the named embedded digest to be present.
    persist_result(
        request().candidate_pool.candidates[0],
        artifact_root=tmp_path,
        gameweek_id="GW",
        request_id="r",
    )
    hashless = tmp_path / "hashless.json"
    hashless_pool = request().candidate_pool.model_copy(update={"snapshot_sha256": None})
    hashless.write_bytes(canonical_json_bytes(hashless_pool))
    hashless.with_suffix(".sha256").write_bytes(
        f"{sha256_bytes(hashless.read_bytes())}  {hashless.name}\n".encode("ascii")
    )
    with pytest.raises(OptimisationError, match="invalid artifact"):
        load_verified_artifact(hashless, CandidatePoolSnapshot)

    monkeypatch.setattr(artifacts.Path, "is_symlink", lambda _path: True)
    with pytest.raises(OptimisationError, match="root cannot itself be a symbolic link"):
        artifacts._contained_directory(tmp_path, gameweek_id="GW", request_id="r")
    monkeypatch.undo()

    monkeypatch.setattr(
        artifacts.Path,
        "is_symlink",
        lambda path: path.name == "leaf.json",
    )
    with pytest.raises(OptimisationError, match="destination cannot be a symbolic link"):
        artifacts._write_once(tmp_path / "leaf.json", b"bytes", root=tmp_path)
    monkeypatch.undo()

    monkeypatch.setattr(artifacts.Path, "resolve", lambda _path: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OptimisationError, match="artifact path escapes"):
        artifacts._contained_directory(tmp_path, gameweek_id="GW", request_id="r")
    monkeypatch.undo()

    monkeypatch.setattr(
        artifacts.Path,
        "relative_to",
        lambda _path, _root: (_ for _ in ()).throw(ValueError()),
    )
    with pytest.raises(OptimisationError, match="artifact path escapes"):
        artifacts._write_once(tmp_path / "escaped.json", b"bytes", root=tmp_path)
    monkeypatch.undo()

    destination = tmp_path / "race.json"

    def colliding_link(_source: Path, target: Path) -> None:
        target.write_bytes(b"competing bytes")
        raise FileExistsError

    monkeypatch.setattr(artifacts.os, "link", colliding_link)
    with pytest.raises(OptimisationError, match="immutable artifact collision"):
        artifacts._write_once(destination, b"expected bytes", root=tmp_path)
    monkeypatch.undo()

    def identical_link(_source: Path, target: Path) -> None:
        target.write_bytes(b"expected bytes")
        raise FileExistsError

    monkeypatch.setattr(artifacts.os, "link", identical_link)
    artifacts._write_once(tmp_path / "same-race.json", b"expected bytes", root=tmp_path)
