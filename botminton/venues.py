"""Supported venues and their ayo.co.id identifiers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Venue:
    """A badminton venue that the bot can look up."""

    key: str
    label: str
    ayo_id: int


VENUES: dict[str, Venue] = {
    "kukusan": Venue(key="kukusan", label="Kukusan", ayo_id=307),
    "sima": Venue(key="sima", label="Sima", ayo_id=726),
}


def resolve_venue(value: str) -> Venue | None:
    """Look up a venue by its command key, case-insensitively."""
    return VENUES.get(value.strip().lower())
