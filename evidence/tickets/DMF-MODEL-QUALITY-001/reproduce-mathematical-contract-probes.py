"""Reproduce frozen contract risks offline; no forecasts, labels, or model changes."""

import json
from decimal import Decimal

from pydantic import ValidationError

from dmf_pulse.evaluation.distribution_metrics import discrete_quantile, ranked_probability_score
from dmf_pulse.optimisation.multi_gameweek_models import TacticalNodeEvaluation


def main() -> None:
    sparse = {Decimal(0): Decimal(".5"), Decimal(2): Decimal(".5")}
    filled = sparse | {Decimal(1): Decimal(0)}
    sparse_score = ranked_probability_score(sparse, Decimal(1))
    filled_score = ranked_probability_score(filled, Decimal(1))
    if (sparse_score, filled_score) != (Decimal(".25"), Decimal(".50")):
        raise ValueError("FROZEN_METRIC_CONTRACT_BEHAVIOUR_CHANGED")
    pmf = {Decimal(0): Decimal(".95"), Decimal(10): Decimal(".05")}
    mean = sum((value * probability for value, probability in pmf.items()), Decimal(0))
    p10 = discrete_quantile(pmf, Decimal(".1"))
    p90 = discrete_quantile(pmf, Decimal(".9"))
    rejected = False
    try:
        TacticalNodeEvaluation(
            expected_points=mean,
            p10_points=p10,
            p90_points=p90,
            tactical_plan_sha256="1" * 64,
            tactical_plan={},
            exact_stage10_evaluation=True,
            source="FROZEN_STAGE10_RECORD",
        )
    except ValidationError as error:
        rejected = any(
            "tactical p10, mean and p90 must be monotone" in item["msg"] for item in error.errors()
        )
    if not rejected or mean != Decimal(".50") or p10 != 0 or p90 != 0:
        raise ValueError("FROZEN_TACTICAL_CONTRACT_BEHAVIOUR_CHANGED")
    print(
        json.dumps(
            {
                "classification": "OWNED_MATHEMATICAL_COUNTEREXAMPLES_NOT_PREDICTIVE_VALIDATION",
                "sparse_rps": str(sparse_score),
                "zero_filled_rps": str(filled_score),
                "rare_tail_mean": str(mean),
                "p10": str(p10),
                "p90": str(p90),
                "valid_tail_rejected": rejected,
                "accepted_modules_modified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
