from __future__ import annotations

import json
from decimal import Decimal

import pytest

from dmf_pulse.prices.models import PriceMass, PricePmf
from dmf_pulse.prices.selling_value import selling_value_distribution
from dmf_pulse.prices.service import PriceService
from tests.prices_helpers import selling_rule, spell

pytestmark = pytest.mark.golden


def test_validation_report_matches_independent_review_golden(repository_root) -> None:
    expected = json.loads(
        (repository_root / "tests/golden/prices/validation_report.json").read_text(encoding="utf-8")
    )
    assert PriceService().validate().model_dump(mode="json") == expected


@pytest.mark.parametrize(
    ("purchase", "current", "expected"),
    ((50, 47, 47), (50, 50, 50), (50, 51, 50), (50, 54, 52), (50, 55, 52)),
)
def test_stage11_selling_value_matches_hand_calculated_oracle(
    purchase: int, current: int, expected: int
) -> None:
    market = PricePmf(support=(PriceMass(price_units=current, probability=Decimal(1)),))
    value = selling_value_distribution(
        spell(purchase=purchase, current=current), market, rule=selling_rule()
    )
    assert value.support[0].price_units == expected
