"""D7 evidence builder rejects tampered identities and probe governance drift."""

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from dmf_pulse.assurance.canonical import canonical_sha256

pytestmark = pytest.mark.unit

_BUILDER_PATH = (
    Path(__file__).resolve().parents[3] / "scripts/build_team_strength_l7_d7_evidence.py"
)
_BUILDER_SPEC = importlib.util.spec_from_file_location("d7_evidence_builder", _BUILDER_PATH)
assert _BUILDER_SPEC is not None and _BUILDER_SPEC.loader is not None
_BUILDER_MODULE = importlib.util.module_from_spec(_BUILDER_SPEC)
sys.modules[_BUILDER_SPEC.name] = _BUILDER_MODULE
_BUILDER_SPEC.loader.exec_module(_BUILDER_MODULE)
_require_probe_contract = _BUILDER_MODULE._require_probe_contract
_validated_decision_value = _BUILDER_MODULE._validated_decision_value


def _decision_value() -> dict[str, object]:
    plan = {
        "current_action": {"node_id": "n0"},
        "future_policy": [{"node_id": "n1"}, {"node_id": "n2"}],
        "utility": {"objective_total": "1"},
    }
    return {
        "recommended": plan,
        "no_transfer_baseline": deepcopy(plan),
        "root_counterfactual": deepcopy(plan),
        "conservative_alternative": {
            "availability": "DISTINCT",
            "reason": "synthetic",
            "plan": deepcopy(plan),
        },
        "high_upside_alternative": {
            "availability": "DISTINCT",
            "reason": "synthetic",
            "plan": deepcopy(plan),
        },
        "transfer_count_frontier": [{"transfer_count": 0}],
    }


def _probe(*, high: bool = False) -> dict[str, object]:
    generated, retained, actions = (
        (10000000, 10000000, 10000000) if high else (2097152, 786432, 2097152)
    )
    return {
        "projection_ordering": "baseline",
        "source": "REPOSITORY_OWNED_SYNTHETIC_ONLY",
        "stress_case": "L6_SHAPE_13_INCOMING",
        "effective_max_actions_per_state": 17000,
        "effective_max_returned_root_candidates": 8386,
        "root_action_upper": 8386,
        "candidate_pool_size": 35,
        "fixture_extra_players_per_position": 5,
        "root_incoming_by_position": {"GK": 3, "DEF": 4, "MID": 3, "FWD": 3},
        "terminal_incoming_by_position": {"GK": 3, "DEF": 4, "MID": 3, "FWD": 3},
        "terminal_retained_incoming_count": 13,
        "retained_incoming_count": 13,
        "root_terminal_incoming_overlap": 6,
        "configured_max_policy_candidates": None,
        "configured_max_generated_policy_candidates": generated,
        "configured_max_retained_pareto_candidates": retained,
        "configured_cumulative_legal_action_limit": actions,
    }


def test_decision_semantic_claim_is_recomputed_and_required_shape_is_checked() -> None:
    value = _decision_value()
    validated, claimed = _validated_decision_value(
        {"value": value, "semantic_sha256": canonical_sha256(value)}
    )
    assert validated == value
    assert claimed == canonical_sha256(value)
    with pytest.raises(ValueError, match="authentication failed"):
        _validated_decision_value({"value": value, "semantic_sha256": "0" * 64})
    malformed = deepcopy(value)
    recommended = malformed["recommended"]
    assert isinstance(recommended, dict)
    recommended["future_policy"] = [{"node_id": "n1"}]
    with pytest.raises(ValueError, match="complete future policy"):
        _validated_decision_value(
            {"value": malformed, "semantic_sha256": canonical_sha256(malformed)}
        )
    missing_objective = deepcopy(value)
    del missing_objective["high_upside_alternative"]
    with pytest.raises(ValueError, match="supported objective alternative"):
        _validated_decision_value(
            {
                "value": missing_objective,
                "semantic_sha256": canonical_sha256(missing_objective),
            }
        )


def test_probe_contract_binds_ordering_caps_and_declared_shape() -> None:
    governed = _probe()
    reference = _probe(high=True)
    _require_probe_contract(governed, reference, ordering="BASELINE_LIKE")
    for field, replacement in (
        ("projection_ordering", "shifted-shadow"),
        ("configured_max_generated_policy_candidates", 2097151),
        ("effective_max_actions_per_state", 16999),
        ("root_action_upper", 8385),
    ):
        tampered = deepcopy(governed)
        tampered[field] = replacement
        with pytest.raises(ValueError):
            _require_probe_contract(tampered, reference, ordering="BASELINE_LIKE")
