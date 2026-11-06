"""Pure scheduling helpers: parsing, merging, and rendering time slots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, Sequence

MINUTES_PER_DAY = 24 * 60
_TIME_FORMATS = ("%H:%M", "%H:%M:%S")


@dataclass(frozen=True, slots=True)
class TimeSlot:
    """A contiguous availability range expressed in minutes from midnight.

    ``end_minutes`` can exceed 1440 for ranges that cross midnight, so
    ``23:00 - 00:00`` is stored as ``1380 - 1440``.
    """

    start_minutes: int
    end_minutes: int

    def __post_init__(self) -> None:
        if not 0 <= self.start_minutes < MINUTES_PER_DAY:
            raise ValueError(f"invalid slot start: {self.start_minutes}")
        if self.end_minutes <= self.start_minutes:
            raise ValueError("slot end must be after slot start")
        if self.end_minutes - self.start_minutes > MINUTES_PER_DAY:
            raise ValueError("slots cannot be longer than 24 hours")

    @property
    def start_time(self) -> time:
        return _minutes_to_time(self.start_minutes)

    @property
    def end_time(self) -> time:
        return _minutes_to_time(self.end_minutes)


@dataclass(frozen=True, slots=True)
class Availability:
    """Result of looking up one venue on one day."""

    day: str
    target_date: date
    is_open: bool
    slots: tuple[TimeSlot, ...]


def _minutes_to_time(total_minutes: int) -> time:
    normalized = total_minutes % MINUTES_PER_DAY
    return time(hour=normalized // 60, minute=normalized % 60)


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def parse_time(value: str) -> time:
    """Parse an ``HH:MM`` or ``HH:MM:SS`` time string."""
    if not isinstance(value, str):
        raise ValueError(f"invalid time value: {value!r}")

    text = value.strip()
    for time_format in _TIME_FORMATS:
        try:
            return datetime.strptime(text, time_format).time()
        except ValueError:
            continue

    raise ValueError(f"invalid time value: {value!r}")


def build_slot(start: str, end: str) -> TimeSlot:
    """Build a validated :class:`TimeSlot` from two API time strings."""
    start_minutes = _time_to_minutes(parse_time(start))
    end_minutes = _time_to_minutes(parse_time(end))

    if end_minutes < start_minutes:
        end_minutes += MINUTES_PER_DAY
    elif end_minutes == start_minutes:
        raise ValueError("zero-length availability slot")

    return TimeSlot(start_minutes=start_minutes, end_minutes=end_minutes)


def merge_slots(slots: Iterable[TimeSlot]) -> list[TimeSlot]:
    """Merge overlapping or touching slots into the smallest set of ranges."""
    ordered = sorted(set(slots), key=lambda slot: (slot.start_minutes, slot.end_minutes))
    if not ordered:
        return []

    merged = [ordered[0]]
    for slot in ordered[1:]:
        current = merged[-1]
        if slot.start_minutes <= current.end_minutes:
            merged[-1] = TimeSlot(
                start_minutes=current.start_minutes,
                end_minutes=max(current.end_minutes, slot.end_minutes),
            )
        else:
            merged.append(slot)

    return merged


def format_slot(slot: TimeSlot) -> str:
    return f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}"


def render_availability(
    venue_label: str,
    day: str,
    target_date: date,
    slots: Sequence[TimeSlot],
) -> str:
    joined_slots = "\n".join(format_slot(slot) for slot in slots)
    return (
        f"\nBerikut jadwal GOR {venue_label} yang tersedia untuk Hari {day}, "
        f"Tanggal {target_date.isoformat()}:\n\n{joined_slots}\n  "
    )


def render_not_open(day: str, target_date: date) -> str:
    return f"Maaf, jadwal untuk {day}, {target_date.isoformat()} belum dibuka"


def render_full(day: str, target_date: date) -> str:
    return f"Maaf, jadwal untuk {day}, {target_date.isoformat()} sudah penuh"
