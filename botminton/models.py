"""Domain models for badminton events and their participants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ParticipantStatus(str, Enum):
    """Where a participant currently sits on the event card."""

    ATTENDANCE = "attendance"
    PAID = "paid"


@dataclass(slots=True)
class Participant:
    """One person on an event's attendance or payment list."""

    id: str
    name: str
    status: ParticipantStatus = ParticipantStatus.ATTENDANCE
    user_id: int | None = None
    added_by: int | None = None
    added_at: datetime | None = None
    paid_by: int | None = None
    paid_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "user_id": self.user_id,
            "added_by": self.added_by,
            "added_at": self.added_at.isoformat() if self.added_at else None,
            "paid_by": self.paid_by,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Participant:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            status=ParticipantStatus(str(data.get("status", ParticipantStatus.ATTENDANCE.value))),
            user_id=_optional_int(data.get("user_id")),
            added_by=_optional_int(data.get("added_by")),
            added_at=_parse_optional_datetime(data.get("added_at")),
            paid_by=_optional_int(data.get("paid_by")),
            paid_at=_parse_optional_datetime(data.get("paid_at")),
        )


@dataclass(slots=True)
class Event:
    """A badminton session with its attendance and payment lists."""

    id: str
    guild_id: int
    channel_id: int
    message_id: int
    title: str
    venue: str
    court: str
    start_at: datetime
    end_at: datetime
    price: int
    created_by: int
    created_by_name: str
    created_at: datetime
    maps_url: str | None = None
    notes: str | None = None
    participants: list[Participant] = field(default_factory=list)

    @property
    def attendance(self) -> list[Participant]:
        """Everyone who signed up, including those who have paid."""
        return list(self.participants)

    @property
    def paid(self) -> list[Participant]:
        """The subset of attendees who have been marked as paid."""
        return [
            participant
            for participant in self.participants
            if participant.status is ParticipantStatus.PAID
        ]

    def find_participant(self, participant_id: str) -> Participant | None:
        return next(
            (
                participant
                for participant in self.participants
                if participant.id == participant_id
            ),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "title": self.title,
            "venue": self.venue,
            "court": self.court,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "price": self.price,
            "maps_url": self.maps_url,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_by_name": self.created_by_name,
            "created_at": self.created_at.isoformat(),
            "participants": [
                participant.to_dict() for participant in self.participants
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        return cls(
            id=str(data["id"]),
            guild_id=int(data["guild_id"]),
            channel_id=int(data["channel_id"]),
            message_id=int(data.get("message_id") or 0),
            title=str(data["title"]),
            venue=str(data["venue"]),
            court=str(data["court"]),
            start_at=datetime.fromisoformat(str(data["start_at"])),
            end_at=datetime.fromisoformat(str(data["end_at"])),
            price=int(data["price"]),
            maps_url=_optional_str(data.get("maps_url")),
            notes=_optional_str(data.get("notes")),
            created_by=int(data["created_by"]),
            created_by_name=str(data.get("created_by_name") or "tidak diketahui"),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            participants=[
                Participant.from_dict(participant)
                for participant in data.get("participants", [])
            ],
        )


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
