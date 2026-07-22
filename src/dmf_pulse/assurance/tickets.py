"""Validated ticket identifiers and repository-local ticket paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TICKET_ID_PATTERN = re.compile(r"^[A-Z0-9]+(?:[-.][A-Z0-9]+)*$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class TicketIdError(ValueError):
    """A ticket identifier is unsafe or outside the public contract."""


def validate_ticket_id(value: str) -> str:
    """Return an exact safe ticket ID without normalization."""

    if not isinstance(value, str) or not 3 <= len(value) <= 40:
        raise TicketIdError("ticket ID must contain 3 to 40 characters")
    if TICKET_ID_PATTERN.fullmatch(value) is None:
        raise TicketIdError(
            "ticket ID must use uppercase letters/digits separated by single '-' or '.' characters"
        )
    if ".." in value:
        raise TicketIdError("ticket ID cannot contain repeated dots")
    if value.split(".", maxsplit=1)[0] in WINDOWS_RESERVED_NAMES:
        raise TicketIdError("ticket ID cannot be a reserved cross-platform path name")
    return value


@dataclass(frozen=True, slots=True)
class TicketPaths:
    """All derived paths for one validated ticket."""

    ticket_id: str
    ticket: Path
    evidence: Path
    review: Path
    review_zip: Path


def ticket_paths(root: Path, ticket_id: str) -> TicketPaths:
    """Derive contained paths from a validated ticket identifier."""

    validated = validate_ticket_id(ticket_id)
    return TicketPaths(
        ticket_id=validated,
        ticket=root / "tickets" / validated,
        evidence=root / "evidence" / "tickets" / validated,
        review=root / "review_pack" / validated,
        review_zip=root / "review_pack" / validated / f"DMF_PULSE_{validated}_REVIEW.zip",
    )
