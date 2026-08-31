"""Market-free public contract for an independent-Poisson score prior."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from dmf_pulse.football_events._decimal import canonical_decimal_text, nonnegative_decimal

CANONICAL_NONNEGATIVE_MEASURE_PATTERN = r"^\d+\.\d{6}$"
NonnegativeMeasureJsonInput = Annotated[
    str,
    Field(pattern=CANONICAL_NONNEGATIVE_MEASURE_PATTERN),
]


class ScorePriorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_family: Literal["INDEPENDENT_POISSON_V1"] = "INDEPENDENT_POISSON_V1"
    home_goal_rate: Decimal
    away_goal_rate: Decimal

    @field_validator(
        "home_goal_rate",
        "away_goal_rate",
        mode="before",
        json_schema_input_type=NonnegativeMeasureJsonInput,
    )
    @classmethod
    def validate_rate(cls, value: object, info: ValidationInfo) -> Decimal:
        if info.mode == "json" and (
            not isinstance(value, str)
            or re.fullmatch(CANONICAL_NONNEGATIVE_MEASURE_PATTERN, value) is None
        ):
            raise ValueError(f"{info.field_name} must use its canonical public decimal string")
        return nonnegative_decimal(value, label=str(info.field_name))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        del deep
        data = self.model_dump(mode="python", exclude_none=False)
        if update:
            data.update(dict(update))
        return type(self).model_validate(data)

    def public_dict(self) -> dict[str, str]:
        return {
            "away_goal_rate": canonical_decimal_text(self.away_goal_rate),
            "home_goal_rate": canonical_decimal_text(self.home_goal_rate),
            "model_family": self.model_family,
        }


__all__ = ["ScorePriorRequest"]
