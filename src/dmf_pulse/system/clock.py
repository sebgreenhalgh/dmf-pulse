"""Injectable UTC clock boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Provide aware UTC timestamps."""

    def now_utc(self) -> datetime:
        """Return the current aware UTC time."""


class SystemClock:
    """Production clock using the standard-library UTC source."""

    def now_utc(self) -> datetime:
        """Return the current aware UTC time."""

        return datetime.now(UTC)
