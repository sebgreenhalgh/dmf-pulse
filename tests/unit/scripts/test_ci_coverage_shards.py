from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest
from coverage import Coverage, CoverageData

pytestmark = pytest.mark.unit
SCRIPT = Path("scripts/ci_coverage_shards.py")
GIT_SHA = "a" * 40


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_coverage_shards", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nodeids() -> tuple[str, ...]:
    return (
        "tests/unit/alpha/test_first.py::test_a",
        "tests/unit/alpha/test_first.py::test_b[value with spaces]",
        "tests/unit/beta/test_second.py::TestGroup::test_c",
        "tests/contract/gamma/test_third.py::test_d",
        "tests/golden/delta/test_fourth.py::test_e",
    )


def _write_plan(module: ModuleType, root: Path, *, shard_count: int = 2) -> tuple[dict, Path]:
    plan = module.build_plan(_nodeids(), shard_count=shard_count, git_sha=GIT_SHA)
    module.write_plan_outputs(plan, root)
    return plan, root / "plan.json"


def _coverage_data(path: Path, *, branch: bool = True, source: str = "source.py") -> None:
    data = CoverageData(basename=str(path))
    if branch:
        data.add_arcs({source: {(1, 2), (2, -1)}})
    else:
        data.add_lines({source: {1, 2}})
    data.write()


def _materialize_all(
    module: ModuleType,
    tmp_path: Path,
    *,
    shard_count: int = 2,
) -> tuple[dict, Path, Path]:
    plan, plan_path = _write_plan(module, tmp_path / "plan", shard_count=shard_count)
    artifact_root = tmp_path / "artifacts"
    for index in range(shard_count):
        data_path = tmp_path / f"input-{index}.coverage"
        _coverage_data(data_path, source=f"source-{index}.py")
        module.materialize_shard(
            plan_path=plan_path,
            shard_index=index,
            coverage_data=data_path,
            output_dir=artifact_root / f"coverage-shard-{GIT_SHA}-{index}",
            expected_git_sha=GIT_SHA,
        )
    return plan, plan_path, artifact_root


def test_identical_population_is_deterministic_independent_of_input_order() -> None:
    module = _module()
    forward = module.build_plan(_nodeids(), shard_count=3, git_sha=GIT_SHA)
    reverse = module.build_plan(reversed(_nodeids()), shard_count=3, git_sha=GIT_SHA)
    assert forward == reverse
    assert module._canonical_json(forward) == module._canonical_json(reverse)


def test_partition_union_is_complete_disjoint_and_exactly_once() -> None:
    module = _module()
    plan = module.build_plan(_nodeids(), shard_count=3, git_sha=GIT_SHA)
    shards = plan["shards"]
    assigned = [nodeid for shard in shards for nodeid in shard["nodeids"]]
    assert sorted(assigned) == sorted(_nodeids())
    assert len(assigned) == len(set(assigned))
    assert plan["partition"] == {
        "complete": True,
        "duplicate_nodeid_count": 0,
        "omitted_nodeid_count": 0,
        "unexpected_nodeid_count": 0,
    }


def test_nodeid_path_normalization_preserves_parameter_suffix_verbatim() -> None:
    module = _module()
    raw = r"tests\unit\rules\test_ids.py::test_ticket[RUL\002]"
    normalized = module.normalize_nodeid(raw)
    assert normalized == r"tests/unit/rules/test_ids.py::test_ticket[RUL\002]"
    assert normalized.partition("::")[2] == raw.partition("::")[2]


def test_slash_equivalent_duplicate_nodeids_fail_closed() -> None:
    module = _module()
    with pytest.raises(module.ShardPlannerError, match="duplicate nodeids"):
        module.build_plan(
            (
                r"tests\unit\test_example.py::test_same",
                "tests/unit/test_example.py::test_same",
            ),
            shard_count=1,
            git_sha=GIT_SHA,
        )


@pytest.mark.parametrize(
    "nodeid",
    [
        "",
        "tests/unit/test_example.py",
        "tests/unit/test_example.py::",
        "../tests/unit/test_example.py::test_one",
        "/tests/unit/test_example.py::test_one",
        r"C:\tests\unit\test_example.py::test_one",
        "src/test_example.py::test_one",
        "tests/unit/test_example.txt::test_one",
        "tests/unit/test_example.py::test_one\nforged",
    ],
)
def test_malformed_or_unsafe_nodeids_fail_closed(nodeid: str) -> None:
    module = _module()
    with pytest.raises(module.ShardPlannerError):
        module.normalize_nodeid(nodeid)


def test_module_nodeids_are_kept_together() -> None:
    module = _module()
    plan = module.build_plan(_nodeids(), shard_count=3, git_sha=GIT_SHA)
    owners = {
        nodeid: shard["shard_index"] for shard in plan["shards"] for nodeid in shard["nodeids"]
    }
    assert owners[_nodeids()[0]] == owners[_nodeids()[1]]


def test_heavy_override_uses_deterministic_lightest_shard_tie_break() -> None:
    module = _module()
    heavy = "tests/assurance/optimisation/test_r2c_artifact_validation.py::test_heavy"
    nodeids = (
        heavy,
        "tests/unit/a/test_a.py::test_a",
        "tests/unit/b/test_b.py::test_b",
    )
    plan = module.build_plan(nodeids, shard_count=2, git_sha=GIT_SHA)
    assert plan["shards"][0]["nodeids"] == [heavy]
    assert plan["shards"][0]["estimated_weight"] == 1050
    assert plan["shards"][1]["nodeids"] == sorted(nodeids[1:])


@pytest.mark.parametrize("shard_count", [True, 0, -1, 5])
def test_invalid_or_unavoidably_empty_shard_count_fails(shard_count: int) -> None:
    module = _module()
    with pytest.raises(module.ShardPlannerError, match="shard_count"):
        module.build_plan(_nodeids(), shard_count=shard_count, git_sha=GIT_SHA)


def test_manifest_digest_uses_sorted_utf8_nodeids_with_trailing_lf() -> None:
    module = _module()
    plan = module.build_plan(_nodeids(), shard_count=2, git_sha=GIT_SHA)
    expected = hashlib.sha256(
        "".join(f"{item}\n" for item in sorted(_nodeids())).encode()
    ).hexdigest()
    assert plan["eligible_nodeid_sha256"] == expected
    payload = dict(plan)
    payload.pop("plan_sha256")
    assert plan["plan_sha256"] == hashlib.sha256(module._canonical_json(payload)).hexdigest()
    assert json.loads(module._canonical_json(plan)) == plan


def test_plan_validation_rejects_tampered_digest_and_missing_shard() -> None:
    module = _module()
    plan = module.build_plan(_nodeids(), shard_count=2, git_sha=GIT_SHA)
    bad_digest = copy.deepcopy(plan)
    bad_digest["shards"][0]["nodeid_sha256"] = "0" * 64
    with pytest.raises(module.ShardPlannerError, match="plan_sha256"):
        module.validate_plan(bad_digest)
    bad_digest["plan_sha256"] = module._plan_sha256(bad_digest)
    with pytest.raises(module.ShardPlannerError, match="digest"):
        module.validate_plan(bad_digest)
    missing = copy.deepcopy(plan)
    missing["shards"].pop()
    missing["plan_sha256"] = module._plan_sha256(missing)
    with pytest.raises(module.ShardPlannerError, match="shard_count"):
        module.validate_plan(missing)


def test_plan_outputs_are_canonical_resumable_and_refuse_different_overwrite(
    tmp_path: Path,
) -> None:
    module = _module()
    plan = module.build_plan(_nodeids(), shard_count=2, git_sha=GIT_SHA)
    output_dir = tmp_path / "outputs"
    outputs = module.write_plan_outputs(plan, output_dir)
    assert {path.name for path in outputs} == {"plan.json", "shard-00.args", "shard-01.args"}
    assert (output_dir / "plan.json").read_bytes() == module._canonical_json(plan)
    module.write_plan_outputs(plan, output_dir)
    (output_dir / "plan.json").write_text("different", encoding="utf-8")
    with pytest.raises(module.ShardPlannerError, match="overwrite"):
        module.write_plan_outputs(plan, output_dir)


def test_collection_uses_exact_marker_and_normalizes_plugin_nodeids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def fake_main(arguments: list[str], *, plugins: list[object]) -> pytest.ExitCode:
        assert arguments[-2:] == ["-m", "not performance"]
        plugins[0].nodeids = (r"tests\unit\test_x.py::test_x[RUL\002]",)
        return pytest.ExitCode.OK

    monkeypatch.setattr(module.pytest, "main", fake_main)
    assert module.collect_eligible_nodeids() == (r"tests/unit/test_x.py::test_x[RUL\002]",)


def test_materialize_emits_visible_branch_data_and_bound_metadata(tmp_path: Path) -> None:
    module = _module()
    plan, plan_path = _write_plan(module, tmp_path / "plan")
    data_path = tmp_path / ".coverage"
    _coverage_data(data_path)
    visible, metadata_path = module.materialize_shard(
        plan_path=plan_path,
        shard_index=0,
        coverage_data=data_path,
        output_dir=tmp_path / "artifact",
        expected_git_sha=GIT_SHA,
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert visible.name == "coverage-data-shard-00"
    assert metadata["coverage_has_arcs"] is True
    assert metadata["git_sha"] == GIT_SHA
    assert metadata["plan_sha256"] == plan["plan_sha256"]
    assert metadata["assigned_nodeid_sha256"] == plan["shards"][0]["nodeid_sha256"]
    assert metadata["coverage_data_bytes"] == visible.stat().st_size
    assert metadata["coverage_data_sha256"] == hashlib.sha256(visible.read_bytes()).hexdigest()


def test_materialize_rejects_line_only_data(tmp_path: Path) -> None:
    module = _module()
    _, plan_path = _write_plan(module, tmp_path / "plan")
    data_path = tmp_path / ".coverage"
    _coverage_data(data_path, branch=False)
    with pytest.raises(module.ShardPlannerError, match="line-only"):
        module.materialize_shard(
            plan_path=plan_path,
            shard_index=0,
            coverage_data=data_path,
            output_dir=tmp_path / "artifact",
            expected_git_sha=GIT_SHA,
        )


def test_recursive_artifact_verification_stages_exact_combine_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    plan, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    staged = module.verify_artifacts(
        plan_path=plan_path,
        artifact_root=artifact_root,
        combine_dir=tmp_path / "combine",
        git_sha=GIT_SHA,
        collected_nodeids=_nodeids(),
    )
    assert {path.name for path in staged} == {".coverage.shard-00", ".coverage.shard-01"}
    assert all(path.is_file() for path in staged)
    assert plan["partition"]["complete"] is True


def test_staged_visible_payloads_combine_as_branch_coverage_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    combine_dir = tmp_path / "combine-inputs"
    module.verify_artifacts(
        plan_path=plan_path,
        artifact_root=artifact_root,
        combine_dir=combine_dir,
        git_sha=GIT_SHA,
        collected_nodeids=_nodeids(),
    )
    combined_path = tmp_path / "combined" / ".coverage"
    combined_path.parent.mkdir()
    combined = Coverage(data_file=str(combined_path))
    combined.combine(data_paths=[str(combine_dir)], keep=True)
    combined.save()
    data = CoverageData(basename=str(combined_path))
    data.read()
    assert data.has_arcs()
    assert set(data.measured_files()) == {"source-0.py", "source-1.py"}


def test_artifact_verification_rejects_missing_and_extra_shards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    metadata = artifact_root / f"coverage-shard-{GIT_SHA}-1" / "shard-01.json"
    metadata_bytes = metadata.read_bytes()
    metadata.unlink()
    with pytest.raises(module.ShardPlannerError, match="missing"):
        module.verify_artifacts(
            plan_path=plan_path,
            artifact_root=artifact_root,
            combine_dir=tmp_path / "combine-missing",
            git_sha=GIT_SHA,
            collected_nodeids=_nodeids(),
        )
    metadata.write_bytes(metadata_bytes)
    shutil.copytree(
        artifact_root / f"coverage-shard-{GIT_SHA}-0",
        artifact_root / f"coverage-shard-{GIT_SHA}-02",
    )
    with pytest.raises(module.ShardPlannerError, match="downloaded artifact directories"):
        module.verify_artifacts(
            plan_path=plan_path,
            artifact_root=artifact_root,
            combine_dir=tmp_path / "combine-extra",
            git_sha=GIT_SHA,
            collected_nodeids=_nodeids(),
        )


def test_artifact_verification_rejects_duplicate_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    target = artifact_root / f"coverage-shard-{GIT_SHA}-1" / "shard-01.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["shard_index"] = 0
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.ShardPlannerError, match="index does not match"):
        module.verify_artifacts(
            plan_path=plan_path,
            artifact_root=artifact_root,
            combine_dir=tmp_path / "combine",
            git_sha=GIT_SHA,
            collected_nodeids=_nodeids(),
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("plan_sha256", "0" * 64, "plan_sha256 mismatch"),
        ("coverage_data_bytes", 1, "byte count mismatch"),
    ],
)
def test_artifact_verification_rejects_plan_and_byte_count_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
    message: str,
) -> None:
    module = _module()
    _, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    target = artifact_root / f"coverage-shard-{GIT_SHA}-0" / "shard-00.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload[field] = replacement
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.ShardPlannerError, match=message):
        module.verify_artifacts(
            plan_path=plan_path,
            artifact_root=artifact_root,
            combine_dir=tmp_path / "combine",
            git_sha=GIT_SHA,
            collected_nodeids=_nodeids(),
        )


def test_artifact_verification_rejects_coverage_digest_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    coverage = artifact_root / f"coverage-shard-{GIT_SHA}-0" / "coverage-data-shard-00"
    coverage.write_bytes(coverage.read_bytes() + b"tampered")
    with pytest.raises(module.ShardPlannerError, match="digest mismatch"):
        module.verify_artifacts(
            plan_path=plan_path,
            artifact_root=artifact_root,
            combine_dir=tmp_path / "combine",
            git_sha=GIT_SHA,
            collected_nodeids=_nodeids(),
        )


def test_artifact_verification_rejects_fresh_collection_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, plan_path, artifact_root = _materialize_all(module, tmp_path)
    monkeypatch.setattr(module, "_head_sha", lambda: GIT_SHA)
    with pytest.raises(module.ShardPlannerError, match="fresh pytest collection"):
        module.verify_artifacts(
            plan_path=plan_path,
            artifact_root=artifact_root,
            combine_dir=tmp_path / "combine",
            git_sha=GIT_SHA,
            collected_nodeids=(*_nodeids(), "tests/unit/new/test_new.py::test_new"),
        )


def _coverage_report(*, branch: bool = True, branches: int = 4) -> dict[str, object]:
    return {
        "meta": {"branch_coverage": branch},
        "files": {"src/dmf_pulse/example.py": {"summary": {}}},
        "totals": {
            "covered_branches": min(branches, 3),
            "covered_lines": 9,
            "num_branches": branches,
            "num_statements": 10,
        },
    }


def test_branch_report_proof_requires_explicit_populated_branch_data(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_coverage_report()), encoding="utf-8")
    assert module.verify_branch_report(path) == {
        "covered_branches": 3,
        "num_branches": 4,
        "schema_version": "ci-coverage-branch-proof-v1",
        "status": "PASS",
    }
    path.write_text(json.dumps(_coverage_report(branch=False)), encoding="utf-8")
    with pytest.raises(module.ShardPlannerError, match="line-only"):
        module.verify_branch_report(path)
    path.write_text(json.dumps(_coverage_report(branches=0)), encoding="utf-8")
    with pytest.raises(module.ShardPlannerError, match="zero branches"):
        module.verify_branch_report(path)
