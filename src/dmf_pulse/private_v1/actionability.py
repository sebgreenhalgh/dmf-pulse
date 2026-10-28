"""Transient official-deadline checks, separate from the model information cutoff."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dmf_pulse.assurance.canonical import canonical_sha256
from dmf_pulse.private_v1.errors import PrivateV1Error


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PrivateV1Error(
            "DECISION_CLOCK_INVALID", "Recommendation withheld: execution clock is invalid."
        )
    return value.astimezone(UTC)


class ActionabilityReceipt(BaseModel):
    """Display-lifetime binding only; not permission to persist private decisions."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )
    schema_version: Literal["private-actionability-v1"] = "private-actionability-v1"
    deadline_at: datetime
    checked_at: datetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("deadline_at", "checked_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def valid_binding(self) -> Self:
        if self.checked_at >= self.deadline_at or self.semantic_sha256 != canonical_sha256(
            self.model_dump(mode="json", exclude={"semantic_sha256"})
        ):
            raise ValueError("actionability receipt is invalid")
        return self


class DeadlineGuard:
    """Check monotone execution time without treating the cutoff as an expiry."""

    def __init__(
        self, clock: Callable[[], datetime], *, not_before: datetime | None = None
    ) -> None:
        self._clock = clock
        self._last = None if not_before is None else _utc(not_before)

    def now(self) -> datetime:
        try:
            observed = _utc(self._clock())
        except Exception:
            raise PrivateV1Error(
                "DECISION_CLOCK_INVALID", "Recommendation withheld: execution clock is invalid."
            ) from None
        if self._last is not None and observed < self._last:
            raise PrivateV1Error(
                "DECISION_CLOCK_INVALID",
                "Recommendation withheld: execution clock moved backwards.",
            )
        self._last = observed
        return observed

    @property
    def latest_observed_at(self) -> datetime:
        """Transient high-water mark, including the post-sealing clock sample."""
        if self._last is None:
            raise PrivateV1Error(
                "DECISION_CLOCK_INVALID", "Recommendation withheld: execution clock is invalid."
            )
        return self._last

    def check(self, deadline_at: datetime, *, not_before: datetime | None = None) -> datetime:
        deadline = _utc(deadline_at)
        if not_before is not None:
            floor = _utc(not_before)
            self._last = floor if self._last is None else max(floor, self._last)
        observed = self.now()
        if observed >= deadline:
            raise PrivateV1Error(
                "DECISION_DEADLINE_PASSED",
                "Recommendation withheld: the official Gameweek deadline has been reached.",
            )
        return observed

    def bind(
        self, *, deadline_at: datetime, decision_sha256: str, report: str
    ) -> ActionabilityReceipt:
        value = ActionabilityReceipt.model_construct(
            deadline_at=_utc(deadline_at),
            checked_at=self.check(deadline_at),
            decision_sha256=decision_sha256,
            report_sha256=hashlib.sha256(report.encode()).hexdigest(),
            semantic_sha256="0" * 64,
        )
        payload = value.model_dump(mode="python")
        payload["semantic_sha256"] = canonical_sha256(
            value.model_dump(mode="json", exclude={"semantic_sha256"})
        )
        sealed = ActionabilityReceipt.model_validate(payload)
        self.check(deadline_at)
        return sealed


def require_publication(
    receipt: object,
    *,
    decision_sha256: str,
    report: str,
    now: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    not_before: datetime | None = None,
) -> None:
    """Final CLI boundary: reject altered output, stale receipt or unhealthy clock."""
    try:
        if type(receipt) is not ActionabilityReceipt:
            raise ValueError
        validated = ActionabilityReceipt.model_validate(receipt.model_dump(mode="python"))
        if (
            validated.decision_sha256 != decision_sha256
            or validated.report_sha256 != hashlib.sha256(report.encode()).hexdigest()
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise PrivateV1Error(
            "DECISION_PUBLICATION_INVALID",
            "Recommendation withheld: publication evidence is invalid.",
        ) from None
    if (now is None) == (clock is None):
        raise PrivateV1Error(
            "DECISION_CLOCK_INVALID", "Recommendation withheld: execution clock is invalid."
        )
    floor = validated.checked_at if not_before is None else _utc(not_before)
    if floor < validated.checked_at or floor >= validated.deadline_at:
        raise PrivateV1Error(
            "DECISION_PUBLICATION_INVALID",
            "Recommendation withheld: publication evidence is invalid.",
        )
    publication_clock = clock if clock is not None else lambda: _utc(now)
    DeadlineGuard(publication_clock, not_before=floor).check(validated.deadline_at)


def deadline_notice(deadline_at: datetime) -> str:
    return f"\nACTION DEADLINE\nOfficial Gameweek deadline: {_utc(deadline_at).isoformat()}.\nThis recommendation expires at that deadline; no execution buffer is assumed.\n"


def checked_report(result: object, *, clock: Callable[[], datetime]) -> str:
    """Sanitize malformed service results and final clock failures before any output."""
    try:
        receipt = getattr(result, "actionability", None)
        report = getattr(result, "report", None)
        decision_sha = getattr(getattr(result, "decision", None), "semantic_sha256", None)
        if not isinstance(report, str) or not isinstance(decision_sha, str):
            raise ValueError
        floor = _utc(getattr(result, "publication_not_before", None))
        require_publication(
            receipt, decision_sha256=decision_sha, report=report, clock=clock, not_before=floor
        )
    except (AttributeError, TypeError):
        raise PrivateV1Error(
            "DECISION_PUBLICATION_INVALID",
            "Recommendation withheld: publication evidence is invalid.",
        ) from None
    except ValueError as error:
        if isinstance(error, PrivateV1Error):
            raise
        raise PrivateV1Error(
            "DECISION_PUBLICATION_INVALID",
            "Recommendation withheld: publication evidence is invalid.",
        ) from None
    return report
