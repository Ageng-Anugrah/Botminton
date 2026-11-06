"""Attendance/payment rules and the event card renderer."""

from __future__ import annotations

import uuid
from datetime import datetime

import discord

from botminton.errors import (
    ActionNotAllowedError,
    AlreadyJoinedError,
    AlreadyPaidError,
    DuplicateParticipantError,
    NotPaidError,
    ParticipantNotFoundError,
    ValidationError,
)
from botminton.models import Event, Participant, ParticipantStatus

MAX_NAME_LENGTH = 80
_EMBED_FIELD_LIMIT = 1024
_EMPTY_ATTENDANCE = "Belum ada yang ikut."
_EMPTY_PAID = "Belum ada yang bayar."


def join_event(
    event: Event,
    user_id: int,
    display_name: str,
    now: datetime,
) -> Participant:
    """Add a Discord user to attendance, claiming a matching free-text entry."""
    existing_user = _find_by_user(event, user_id)
    if existing_user is not None:
        if existing_user.status is ParticipantStatus.PAID:
            raise AlreadyJoinedError("Kamu sudah terdaftar dan sudah tercatat lunas.")
        raise AlreadyJoinedError("Kamu sudah terdaftar di attendance.")

    name = normalize_name(display_name)
    existing_name = _find_by_name(event, name)
    if existing_name is not None:
        if existing_name.user_id is None:
            existing_name.user_id = user_id
            return existing_name
        raise DuplicateParticipantError(
            f"Nama **{_escape_name(name)}** sudah dipakai peserta lain. "
            "Minta panitia menambahkan dengan nama yang berbeda."
        )

    participant = Participant(
        id=_new_id(),
        name=name,
        user_id=user_id,
        added_by=user_id,
        added_at=now,
    )
    event.participants.append(participant)
    return participant


def add_participant(
    event: Event,
    name: str,
    actor_id: int,
    now: datetime,
) -> Participant:
    """Add a free-text name to attendance."""
    clean_name = normalize_name(name)
    if _find_by_name(event, clean_name) is not None:
        raise DuplicateParticipantError(
            f"Nama **{_escape_name(clean_name)}** sudah ada di daftar."
        )

    participant = Participant(
        id=_new_id(),
        name=clean_name,
        added_by=actor_id,
        added_at=now,
    )
    event.participants.append(participant)
    return participant


def mark_paid(
    event: Event,
    participant_id: str,
    actor_id: int,
    now: datetime,
) -> Participant:
    """Mark a participant as paid without removing them from attendance."""
    participant = event.find_participant(participant_id)
    if participant is None:
        raise ParticipantNotFoundError()

    if participant.status is ParticipantStatus.PAID:
        raise AlreadyPaidError(
            f"**{_escape_name(participant.name)}** sudah tercatat lunas."
        )

    participant.status = ParticipantStatus.PAID
    participant.paid_by = actor_id
    participant.paid_at = now
    return participant


def mark_self_paid(
    event: Event,
    user_id: int,
    now: datetime,
) -> Participant:
    """Mark the calling user as paid while keeping them in attendance."""
    participant = _find_by_user(event, user_id)
    if participant is None:
        raise ParticipantNotFoundError(
            "Kamu belum terdaftar di attendance. Tekan ✅ Ikut dulu ya."
        )

    if participant.status is ParticipantStatus.PAID:
        raise AlreadyPaidError("Kamu sudah tercatat lunas.")

    participant.status = ParticipantStatus.PAID
    participant.paid_by = user_id
    participant.paid_at = now
    return participant


def unmark_paid(
    event: Event,
    participant_id: str,
    actor_id: int,
) -> Participant:
    """Clear a participant's paid status; they stay in attendance.

    Only the user who recorded the payment or the event creator may undo it.
    """
    participant = event.find_participant(participant_id)
    if participant is None:
        raise ParticipantNotFoundError()

    if participant.status is not ParticipantStatus.PAID:
        raise NotPaidError(
            f"**{_escape_name(participant.name)}** belum tercatat lunas."
        )

    if actor_id != event.created_by and actor_id != participant.paid_by:
        raise ActionNotAllowedError(
            "Hanya yang menandai lunas atau pembuat event yang bisa "
            "membatalkan status ini."
        )

    participant.status = ParticipantStatus.ATTENDANCE
    participant.paid_by = None
    participant.paid_at = None
    return participant


def eligible_paid_for_actor(event: Event, actor_id: int) -> list[Participant]:
    """Paid entries whose paid mark ``actor_id`` is allowed to clear."""
    if actor_id == event.created_by:
        return event.paid
    return [
        participant
        for participant in event.paid
        if participant.paid_by == actor_id
    ]


def unpaid_attendance(event: Event) -> list[Participant]:
    """Attendance entries that have not been marked as paid yet."""
    return [
        participant
        for participant in event.attendance
        if participant.status is not ParticipantStatus.PAID
    ]


def normalize_name(value: str) -> str:
    name = " ".join(value.split()).strip()
    if not name:
        raise ValidationError("Nama tidak boleh kosong.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Nama maksimal {MAX_NAME_LENGTH} karakter.")
    return name


def format_price(price: int) -> str:
    if price <= 0:
        return "Gratis"
    if price % 1000 == 0:
        return f"{price // 1000}k/orang"
    return f"Rp{price:,}/orang".replace(",", ".")


def render_event_embed(event: Event) -> discord.Embed:
    embed = discord.Embed(title=event.title, colour=discord.Colour.gold())

    details = [
        f"📍 : {event.venue}",
        f"🏸 : {event.court}",
        "⏰ : "
        f"{discord.utils.format_dt(event.start_at, 'F')} - "
        f"{discord.utils.format_dt(event.end_at, 't')} "
        f"({discord.utils.format_dt(event.start_at, 'R')})",
        f"💰 : {format_price(event.price)}",
    ]
    if event.maps_url:
        details.append(f"🗺️ : {event.maps_url}")
    if event.notes:
        details.append("")
        details.append("**RULES:**")
        details.append(event.notes[:1500])

    embed.description = "\n".join(details)

    attendees = event.attendance
    paid = event.paid
    embed.add_field(
        name=f"✅ Attendance ({len(attendees)})",
        value=_render_attendance(attendees),
        inline=True,
    )
    embed.add_field(
        name=f"💰 Sudah Bayar ({len(paid)})",
        value=_render_paid(paid),
        inline=True,
    )
    embed.set_footer(text=f"Created by {event.created_by_name}")
    return embed


def _render_attendance(participants: list[Participant]) -> str:
    lines = [
        f"{index}. {_escape_name(participant.name)}"
        for index, participant in enumerate(participants, start=1)
    ]
    return _truncate_lines(lines, _EMPTY_ATTENDANCE)


def _render_paid(participants: list[Participant]) -> str:
    lines = []
    for index, participant in enumerate(participants, start=1):
        marker = (
            f"<@{participant.paid_by}>"
            if participant.paid_by is not None
            else "tidak diketahui"
        )
        lines.append(
            f"{index}. {_escape_name(participant.name)} — oleh {marker}"
        )
    return _truncate_lines(lines, _EMPTY_PAID)


def _truncate_lines(lines: list[str], empty: str) -> str:
    if not lines:
        return empty

    kept: list[str] = []
    used = 0
    for index, line in enumerate(lines):
        extra = len(line) + (1 if kept else 0)
        if used + extra > _EMBED_FIELD_LIMIT - 24:
            remaining = len(lines) - index
            kept.append(f"… +{remaining} lainnya")
            break
        kept.append(line)
        used += extra

    return "\n".join(kept)[:_EMBED_FIELD_LIMIT]


def _escape_name(name: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(name))


def _find_by_name(event: Event, name: str) -> Participant | None:
    folded = name.casefold()
    return next(
        (
            participant
            for participant in event.participants
            if participant.name.casefold() == folded
        ),
        None,
    )


def _find_by_user(event: Event, user_id: int) -> Participant | None:
    return next(
        (
            participant
            for participant in event.participants
            if participant.user_id == user_id
        ),
        None,
    )


def _new_id() -> str:
    return uuid.uuid4().hex[:12]
