"""Pure common-support distribution diagnostics; movement is not accuracy."""

from collections.abc import Callable
from decimal import Decimal, localcontext

from dmf_pulse.football_events.team_strength_model import Number
from dmf_pulse.ingestion.openfootball.team_strength_data import FrozenEvidence


class DistributionMovement(FrozenEvidence):
    interpretation: str = "DECISION_MATERIALITY_NOT_MODEL_ACCURACY"
    metric_deltas: tuple[tuple[str, Number], ...]
    exact_score_total_variation: Number
    exact_score_max_probability_movement: Number
    exact_score_jensen_shannon: Number


def distribution_features(matrix: tuple[tuple[Decimal, ...], ...]) -> dict[str, Decimal]:
    if not matrix or not matrix[0] or any(len(row) != len(matrix[0]) for row in matrix):
        raise ValueError("invalid comparison score matrix shape")
    if any(not x.is_finite() or x < 0 for row in matrix for x in row):
        raise ValueError("invalid comparison score probabilities")
    with localcontext() as context:
        context.prec = 60
        if abs(sum((x for row in matrix for x in row), Decimal(0)) - 1) > Decimal("1e-50"):
            raise ValueError("comparison score matrix not normalized")
        result = {}
        for side in ("home", "away"):
            pmf = (
                tuple(sum(row, Decimal(0)) for row in matrix)
                if side == "home"
                else tuple(
                    sum((row[j] for row in matrix), Decimal(0)) for j in range(len(matrix[0]))
                )
            )
            mean = sum((Decimal(k) * x for k, x in enumerate(pmf)), Decimal(0))
            variance = sum(((Decimal(k) - mean) ** 2 * x for k, x in enumerate(pmf)), Decimal(0))
            quantiles = []
            for threshold in (Decimal("0.1"), Decimal("0.9")):
                cumulative = Decimal(0)
                for k, x in enumerate(pmf):
                    cumulative += x
                    if cumulative >= threshold:
                        quantiles.append(k)
                        break
            result.update(
                {
                    f"{side}_expected_goals": mean,
                    f"{side}_predictive_variance": variance,
                    f"{side}_tail_width_p90_p10": Decimal(quantiles[1] - quantiles[0]),
                }
            )
        predicates: tuple[tuple[str, Callable[[int, int], bool]], ...] = (
            ("home_win", lambda h, a: h > a),
            ("draw", lambda h, a: h == a),
            ("away_win", lambda h, a: h < a),
            ("home_clean_sheet", lambda h, a: a == 0),
            ("away_clean_sheet", lambda h, a: h == 0),
        )
        for name, predicate in predicates:
            result[name] = sum(
                (x for h, row in enumerate(matrix) for a, x in enumerate(row) if predicate(h, a)),
                Decimal(0),
            )
        for line in range(6):
            result[f"total_over_{line}.5"] = sum(
                (x for h, row in enumerate(matrix) for a, x in enumerate(row) if h + a > line),
                Decimal(0),
            )
        return result


def compare_distributions(
    left: tuple[tuple[Decimal, ...], ...], right: tuple[tuple[Decimal, ...], ...]
) -> DistributionMovement:
    lf, rf = distribution_features(left), distribution_features(right)
    with localcontext() as context:
        context.prec = 60
        cells = tuple(
            (
                left[i][j] if i < len(left) and j < len(left[0]) else Decimal(0),
                right[i][j] if i < len(right) and j < len(right[0]) else Decimal(0),
            )
            for i in range(max(len(left), len(right)))
            for j in range(max(len(left[0]), len(right[0])))
        )
        js = Decimal(0)
        for left_value, right_value in cells:
            middle = (left_value + right_value) / 2
            for value in (left_value, right_value):
                if value > 0:
                    js += value * (value / middle).ln() / 2
        return DistributionMovement(
            metric_deltas=tuple((name, rf[name] - lf[name]) for name in sorted(lf)),
            exact_score_total_variation=sum(
                (abs(right_value - left_value) for left_value, right_value in cells), Decimal(0)
            )
            / 2,
            exact_score_max_probability_movement=max(
                abs(right_value - left_value) for left_value, right_value in cells
            ),
            exact_score_jensen_shannon=js,
        )
