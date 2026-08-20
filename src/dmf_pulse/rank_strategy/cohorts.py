"""Rights and weight validation for Stage-15 manager cohorts."""

from __future__ import annotations

from dmf_pulse.rank_strategy.errors import RankStrategyError
from dmf_pulse.rank_strategy.models import CohortSample


def require_permitted_sample(sample: CohortSample) -> CohortSample:
    """Fail closed before manager-level data can enter numerical rank logic."""

    if not sample.rights_status.permitted:
        raise RankStrategyError(
            "RANK_SAMPLE_RIGHTS_INVALID",
            "manager sample rights do not permit Stage-15 numerical use",
            sample_id=sample.sample_id,
            rights_status=sample.rights_status.value,
        )
    return sample


def normalised_member_weights(sample: CohortSample) -> dict[str, float]:
    require_permitted_sample(sample)
    total = sum(member.weight for member in sample.members)
    return {
        member.manager_plan.manager_id: member.weight / total
        for member in sorted(sample.members, key=lambda item: item.manager_plan.manager_id)
    }
