"""Slash command and interactive card for badminton events."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from botminton.errors import (
    BotmintonError,
    EventNotFoundError,
    StoreError,
    ValidationError,
)
from botminton.models import Event
from botminton.services import attendance
from botminton.services.event_store import EventStore

logger = logging.getLogger(__name__)

_MAX_TITLE = 256
_MAX_SHORT = 100
_MAX_NOTES = 1500
_MAX_PRICE = 10_000_000
_SCHEDULE_PATTERN = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})\s+"
    r"(\d{1,2}[:.]\d{2})\s*-\s*(\d{1,2}[:.]\d{2})\s*$"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _validate_title(value: str) -> str:
    title = " ".join(value.split()).strip()
    if not title:
        raise ValidationError("Judul event tidak boleh kosong.")
    if len(title) > _MAX_TITLE:
        raise ValidationError(f"Judul maksimal {_MAX_TITLE} karakter.")
    return title


def _validate_short(value: str, label: str) -> str:
    text = " ".join(value.split()).strip()
    if not text:
        raise ValidationError(f"{label} tidak boleh kosong.")
    if len(text) > _MAX_SHORT:
        raise ValidationError(f"{label} maksimal {_MAX_SHORT} karakter.")
    return text


def _normalise_clock(value: str) -> str:
    parts = re.split(r"[:.]", value.strip())
    if len(parts) != 2:
        raise ValidationError("Format jam harus HH:MM, contoh: 17:00.")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValidationError("Format jam harus HH:MM, contoh: 17:00.") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValidationError("Jam tidak valid. Gunakan format HH:MM, contoh: 17:00.")
    return f"{hour:02d}:{minute:02d}"


def _parse_clock(value: str) -> tuple[int, int]:
    normalised = _normalise_clock(value)
    hour, minute = normalised.split(":")
    return int(hour), int(minute)


def _parse_schedule(
    tanggal: str,
    mulai: str,
    selesai: str,
    tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    try:
        day = datetime.strptime(tanggal.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(
            "Format tanggal harus YYYY-MM-DD, contoh: 2026-11-07."
        ) from exc

    start_hour, start_minute = _parse_clock(mulai)
    end_hour, end_minute = _parse_clock(selesai)

    start_at = datetime(
        day.year, day.month, day.day, start_hour, start_minute, tzinfo=tz
    )
    end_at = datetime(
        day.year, day.month, day.day, end_hour, end_minute, tzinfo=tz
    )
    if end_at <= start_at:
        raise ValidationError("Jam selesai harus setelah jam mulai.")
    return start_at, end_at


def _parse_schedule_text(value: str, tz: ZoneInfo) -> tuple[datetime, datetime]:
    match = _SCHEDULE_PATTERN.match(value)
    if match is None:
        raise ValidationError(
            "Format jadwal: YYYY-MM-DD HH:MM-HH:MM, contoh: 2026-11-07 17:00-19:00."
        )

    tanggal, mulai, selesai = match.groups()
    return _parse_schedule(tanggal, mulai, selesai, tz)


def _parse_price(value: str) -> int:
    text = value.strip().lower().replace("rp", "").replace(" ", "")
    if not text:
        raise ValidationError("Harga tidak boleh kosong.")

    multiplier = 1
    if text.endswith("k"):
        multiplier = 1000
        text = text[:-1].replace(",", ".")
    else:
        text = text.replace(".", "").replace(",", "")

    try:
        price = int(round(float(text) * multiplier))
    except ValueError as exc:
        raise ValidationError(
            "Harga harus berupa angka, contoh: 40000 atau 40k."
        ) from exc

    if not 0 <= price <= _MAX_PRICE:
        raise ValidationError("Harga tidak valid.")
    return price


def _member_name(guild: discord.Guild | None, user_id: int | None) -> str:
    if user_id is None:
        return "tidak diketahui"
    if guild is not None:
        member = guild.get_member(user_id)
        if member is not None:
            return member.display_name
    return f"pengguna {user_id}"


def _user_error(error: Exception) -> str:
    if isinstance(error, EventNotFoundError):
        return str(error)
    if isinstance(error, StoreError):
        return "Gagal mengakses data event. Coba lagi sebentar lagi."
    if isinstance(error, BotmintonError):
        return str(error)
    return "Maaf, terjadi kesalahan. Coba lagi."


async def _send_ephemeral(
    interaction: discord.Interaction,
    message: str,
) -> None:
    allowed = discord.AllowedMentions.none()
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message, ephemeral=True, allowed_mentions=allowed
            )
        else:
            await interaction.response.send_message(
                message, ephemeral=True, allowed_mentions=allowed
            )
    except discord.HTTPException:
        logger.exception("Failed to send an ephemeral response")


def _make_button(
    label: str,
    emoji: str,
    style: discord.ButtonStyle,
    custom_id: str,
    row: int,
    callback,
) -> discord.ui.Button:
    button = discord.ui.Button(
        label=label,
        emoji=emoji,
        style=style,
        custom_id=custom_id,
        row=row,
    )
    button.callback = callback
    return button


class EventCog(commands.Cog):
    """Create and manage badminton event cards."""

    event = app_commands.Group(name="event", description="Kelola event badminton")

    def __init__(
        self,
        bot: commands.Bot,
        store: EventStore,
        timezone: ZoneInfo,
    ) -> None:
        self.bot = bot
        self.store = store
        self.timezone = timezone
        self._locks: dict[str, asyncio.Lock] = {}

    async def cog_load(self) -> None:
        for event in await self.store.list_all():
            self.bot.add_view(
                self.build_view(event.id),
                message_id=event.message_id or None,
            )

    def build_view(self, event_id: str) -> EventCardView:
        return EventCardView(self, event_id)

    def forget_event(self, event_id: str) -> None:
        self._locks.pop(event_id, None)

    @asynccontextmanager
    async def event_lock(self, event_id: str):
        lock = self._locks.setdefault(event_id, asyncio.Lock())
        async with lock:
            yield

    async def require_event(self, event_id: str) -> Event:
        event = await self.store.get(event_id)
        if event is None:
            raise EventNotFoundError(event_id)
        return event

    async def refresh_card(self, event: Event) -> None:
        if not event.message_id:
            return

        channel = self.bot.get_channel(event.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(event.channel_id)
            except discord.HTTPException:
                logger.exception("Failed to fetch channel %s", event.channel_id)
                return

        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("Channel %s is not messageable", event.channel_id)
            return

        try:
            message = await channel.fetch_message(event.message_id)
            await message.edit(
                embed=attendance.render_event_embed(event),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.NotFound:
            logger.warning("Event message %s no longer exists", event.message_id)
        except discord.HTTPException:
            logger.exception("Failed to refresh event card %s", event.message_id)

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        original = getattr(error, "original", error)
        logger.error(
            "Event command failed",
            exc_info=(type(original), original, original.__traceback__),
        )
        await _send_ephemeral(interaction, _user_error(original))

    @event.command(name="create", description="Buat event badminton dan kartu attendance")
    @app_commands.describe(
        judul="Judul event, contoh: Petojo Berbulu 7 Nov 2026",
        tempat="Nama GOR/tempat, contoh: Petojo Arena",
        lapangan="Nama/nomor lapangan, contoh: Lap 2",
        tanggal="Tanggal event dengan format YYYY-MM-DD",
        mulai="Jam mulai dengan format HH:MM",
        selesai="Jam selesai dengan format HH:MM",
        harga="Harga per orang, contoh: 40000",
        peta="Link Google Maps (opsional)",
        catatan="Catatan atau rules event (opsional)",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        judul: str,
        tempat: str,
        lapangan: str,
        tanggal: str,
        mulai: str,
        selesai: str,
        harga: app_commands.Range[int, 0, 10_000_000],
        peta: str | None = None,
        catatan: str | None = None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await _send_ephemeral(
                interaction, "Command ini hanya bisa dipakai di server."
            )
            return

        try:
            title = _validate_title(judul)
            venue = _validate_short(tempat, "Tempat")
            court = _validate_short(lapangan, "Lapangan")
            start_at, end_at = _parse_schedule(
                tanggal, mulai, selesai, self.timezone
            )
            notes = _clean_optional(catatan)
            if notes is not None and len(notes) > _MAX_NOTES:
                raise ValidationError(
                    f"Catatan maksimal {_MAX_NOTES} karakter."
                )
            maps_url = _clean_optional(peta)
            if maps_url is not None and len(maps_url) > 500:
                raise ValidationError("Link peta terlalu panjang.")
            if maps_url is not None and not maps_url.startswith(
                ("http://", "https://")
            ):
                raise ValidationError(
                    "Link peta harus diawali http:// atau https://."
                )
        except ValidationError as exc:
            await _send_ephemeral(interaction, str(exc))
            return

        event = Event(
            id=_new_id(),
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            message_id=0,
            title=title,
            venue=venue,
            court=court,
            start_at=start_at,
            end_at=end_at,
            price=int(harga),
            maps_url=maps_url,
            notes=notes,
            created_by=interaction.user.id,
            created_by_name=interaction.user.display_name,
            created_at=_now(),
        )

        try:
            await self.store.create(event)
        except StoreError:
            logger.exception("Failed to create event")
            await _send_ephemeral(
                interaction, "Gagal menyimpan event. Coba lagi."
            )
            return

        view = self.build_view(event.id)
        try:
            await interaction.response.send_message(
                embed=attendance.render_event_embed(event),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("Failed to send event card")
            await self.store.delete(event.id)
            await _send_ephemeral(
                interaction, "Gagal mengirim kartu event. Coba lagi."
            )
            return

        try:
            message = await interaction.original_response()
        except discord.HTTPException:
            logger.exception("Failed to fetch the sent event card")
            return

        try:
            await self.store.mutate(
                event.id,
                lambda stored: setattr(stored, "message_id", message.id),
            )
        except BotmintonError:
            logger.exception("Failed to save event message id")

        self.bot.add_view(view, message_id=message.id)


class EventCardView(discord.ui.View):
    """Persistent buttons attached to an event card."""

    def __init__(self, cog: EventCog, event_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id

        prefix = f"badminton:{event_id}"
        self.add_item(
            _make_button(
                "Ikut",
                "✅",
                discord.ButtonStyle.success,
                f"{prefix}:join",
                0,
                self._join,
            )
        )
        self.add_item(
            _make_button(
                "Saya sudah bayar",
                "💰",
                discord.ButtonStyle.primary,
                f"{prefix}:self_paid",
                0,
                self._self_paid,
            )
        )
        self.add_item(
            _make_button(
                "Tambah nama",
                "➕",
                discord.ButtonStyle.secondary,
                f"{prefix}:add",
                0,
                self._add_name,
            )
        )
        self.add_item(
            _make_button(
                "Tandai lunas",
                "💸",
                discord.ButtonStyle.secondary,
                f"{prefix}:mark_paid",
                1,
                self._open_mark_paid,
            )
        )
        self.add_item(
            _make_button(
                "Batalkan lunas",
                "↩️",
                discord.ButtonStyle.secondary,
                f"{prefix}:unmark_paid",
                1,
                self._open_unmark_paid,
            )
        )
        self.add_item(
            _make_button(
                "Edit",
                "✏️",
                discord.ButtonStyle.primary,
                f"{prefix}:edit",
                1,
                self._edit,
            )
        )
        self.add_item(
            _make_button(
                "Hapus",
                "🗑️",
                discord.ButtonStyle.danger,
                f"{prefix}:delete",
                1,
                self._delete,
            )
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        if isinstance(error, EventNotFoundError):
            logger.info("Event card action rejected: %s", error)
        elif isinstance(error, StoreError):
            logger.error(
                "Event card action failed",
                exc_info=(type(error), error, error.__traceback__),
            )
        elif isinstance(error, BotmintonError):
            logger.info("Event card action rejected: %s", error)
        else:
            logger.error(
                "Event card action failed",
                exc_info=(type(error), error, error.__traceback__),
            )
        await _send_ephemeral(interaction, _user_error(error))

    async def _update_card(
        self,
        interaction: discord.Interaction,
        event: Event,
    ) -> None:
        await interaction.response.edit_message(
            embed=attendance.render_event_embed(event),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _join(self, interaction: discord.Interaction) -> None:
        async with self.cog.event_lock(self.event_id):
            await self.cog.store.mutate(
                self.event_id,
                lambda event: attendance.join_event(
                    event,
                    interaction.user.id,
                    interaction.user.display_name,
                    _now(),
                ),
            )
            event = await self.cog.require_event(self.event_id)
            await self._update_card(interaction, event)

    async def _self_paid(self, interaction: discord.Interaction) -> None:
        async with self.cog.event_lock(self.event_id):
            await self.cog.store.mutate(
                self.event_id,
                lambda event: attendance.mark_self_paid(
                    event, interaction.user.id, _now()
                ),
            )
            event = await self.cog.require_event(self.event_id)
            await self._update_card(interaction, event)

    async def _add_name(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            AddNameModal(self.cog, self.event_id)
        )

    async def _edit(self, interaction: discord.Interaction) -> None:
        event = await self.cog.require_event(self.event_id)
        if interaction.user.id != event.created_by:
            await _send_ephemeral(
                interaction, "Hanya pembuat event yang bisa mengedit."
            )
            return

        await interaction.response.send_modal(EditEventModal(self.cog, event))

    async def _delete(self, interaction: discord.Interaction) -> None:
        event = await self.cog.require_event(self.event_id)
        if interaction.user.id != event.created_by:
            await _send_ephemeral(
                interaction, "Hanya pembuat event yang bisa menghapus."
            )
            return

        await interaction.response.send_message(
            f"Yakin hapus event **{discord.utils.escape_markdown(event.title)}**?",
            view=ConfirmDeleteView(self.cog, self.event_id),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _open_mark_paid(self, interaction: discord.Interaction) -> None:
        event = await self.cog.require_event(self.event_id)
        candidates = attendance.unpaid_attendance(event)
        if not candidates:
            if event.attendance:
                message = "Semua peserta attendance sudah tercatat lunas."
            else:
                message = "Belum ada peserta di attendance."
            await _send_ephemeral(interaction, message)
            return

        options = [
            discord.SelectOption(
                label=participant.name[:100],
                value=participant.id,
            )
            for participant in candidates[:25]
        ]
        content = "Pilih nama yang sudah bayar. Status akan dicatat atas namamu."
        if len(candidates) > 25:
            content += f"\nMenampilkan 25 dari {len(candidates)} nama."

        await interaction.response.send_message(
            content,
            view=PaidSelectView(
                self.cog, self.event_id, options, unmark=False
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _open_unmark_paid(self, interaction: discord.Interaction) -> None:
        event = await self.cog.require_event(self.event_id)
        eligible = attendance.eligible_paid_for_actor(
            event, interaction.user.id
        )
        if not eligible:
            if not event.paid:
                message = "Belum ada peserta yang berstatus lunas."
            else:
                message = (
                    "Kamu hanya bisa membatalkan status lunas yang kamu "
                    "tandai sendiri."
                )
            await _send_ephemeral(interaction, message)
            return

        options = [
            discord.SelectOption(
                label=participant.name[:100],
                value=participant.id,
                description=(
                    f"Ditandai oleh "
                    f"{_member_name(interaction.guild, participant.paid_by)}"
                )[:100],
            )
            for participant in eligible[:25]
        ]
        content = "Pilih status lunas yang ingin dibatalkan."
        if len(eligible) > 25:
            content += f"\nMenampilkan 25 dari {len(eligible)} nama."

        await interaction.response.send_message(
            content,
            view=PaidSelectView(
                self.cog, self.event_id, options, unmark=True
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class PaidSelectView(discord.ui.View):
    """Ephemeral select menu for marking or unmarking payments."""

    def __init__(
        self,
        cog: EventCog,
        event_id: str,
        options: list[discord.SelectOption],
        *,
        unmark: bool,
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.event_id = event_id
        self.unmark = unmark

        select = discord.ui.Select(
            placeholder="Pilih nama...",
            min_values=1,
            max_values=1,
            options=options,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        participant_id = interaction.data["values"][0]

        try:
            await interaction.response.defer()

            async with self.cog.event_lock(self.event_id):
                if self.unmark:
                    await self.cog.store.mutate(
                        self.event_id,
                        lambda event: attendance.unmark_paid(
                            event, participant_id, interaction.user.id
                        ),
                    )
                    action = "↩️ Status lunas dibatalkan"
                else:
                    await self.cog.store.mutate(
                        self.event_id,
                        lambda event: attendance.mark_paid(
                            event,
                            participant_id,
                            interaction.user.id,
                            _now(),
                        ),
                    )
                    action = "💰 Ditandai lunas"

                event = await self.cog.require_event(self.event_id)
                participant = event.find_participant(participant_id)
                name = participant.name if participant else "Peserta"
                await self.cog.refresh_card(event)

            await interaction.edit_original_response(
                content=f"{action}: **{discord.utils.escape_markdown(name)}**.",
                view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except BotmintonError as exc:
            await interaction.edit_original_response(
                content=_user_error(exc),
                view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("Failed to process a payment selection")
            await interaction.edit_original_response(
                content="Gagal memperbarui kartu event. Coba lagi.",
                view=None,
            )
        except Exception:
            logger.exception("Unexpected error in a payment selection")
            await interaction.edit_original_response(
                content="Maaf, terjadi kesalahan. Coba lagi.",
                view=None,
            )


class AddNameModal(discord.ui.Modal, title="Tambah nama peserta"):
    name = discord.ui.TextInput(
        label="Nama",
        placeholder="Contoh: Bruno",
        min_length=1,
        max_length=attendance.MAX_NAME_LENGTH,
    )

    def __init__(self, cog: EventCog, event_id: str) -> None:
        super().__init__()
        self.cog = cog
        self.event_id = event_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            async with self.cog.event_lock(self.event_id):
                await self.cog.store.mutate(
                    self.event_id,
                    lambda event: attendance.add_participant(
                        event,
                        self.name.value,
                        interaction.user.id,
                        _now(),
                    ),
                )
                event = await self.cog.require_event(self.event_id)
                await interaction.response.edit_message(
                    embed=attendance.render_event_embed(event),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except BotmintonError as exc:
            await _send_ephemeral(interaction, _user_error(exc))
        except discord.HTTPException:
            logger.exception("Failed to update the card after adding a name")
            await _send_ephemeral(
                interaction, "Gagal memperbarui kartu event. Coba lagi."
            )
        except Exception:
            logger.exception("Unexpected error while adding a name")
            await _send_ephemeral(
                interaction, "Maaf, terjadi kesalahan. Coba lagi."
            )


class EditEventModal(discord.ui.Modal, title="Edit event"):
    judul = discord.ui.TextInput(label="Judul", max_length=_MAX_TITLE)
    tempat = discord.ui.TextInput(label="Tempat", max_length=_MAX_SHORT)
    lapangan = discord.ui.TextInput(label="Lapangan", max_length=_MAX_SHORT)
    jadwal = discord.ui.TextInput(
        label="Jadwal",
        placeholder="2026-11-07 17:00-19:00",
        max_length=40,
    )
    harga = discord.ui.TextInput(
        label="Harga per orang",
        placeholder="40000 atau 40k",
        max_length=20,
    )

    def __init__(self, cog: EventCog, event: Event) -> None:
        super().__init__()
        self.cog = cog
        self.event_id = event.id

        self.judul.default = event.title
        self.tempat.default = event.venue
        self.lapangan.default = event.court
        self.jadwal.default = (
            f"{event.start_at:%Y-%m-%d %H:%M}-{event.end_at:%H:%M}"
        )
        self.harga.default = str(event.price)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            title = _validate_title(self.judul.value)
            venue = _validate_short(self.tempat.value, "Tempat")
            court = _validate_short(self.lapangan.value, "Lapangan")
            start_at, end_at = _parse_schedule_text(
                self.jadwal.value, self.cog.timezone
            )
            price = _parse_price(self.harga.value)

            async with self.cog.event_lock(self.event_id):
                def apply(event: Event) -> None:
                    event.title = title
                    event.venue = venue
                    event.court = court
                    event.start_at = start_at
                    event.end_at = end_at
                    event.price = price

                await self.cog.store.mutate(self.event_id, apply)
                event = await self.cog.require_event(self.event_id)
                await interaction.response.edit_message(
                    embed=attendance.render_event_embed(event),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except BotmintonError as exc:
            await _send_ephemeral(interaction, _user_error(exc))
        except discord.HTTPException:
            logger.exception("Failed to update the edited event card")
            await _send_ephemeral(
                interaction, "Gagal memperbarui kartu event. Coba lagi."
            )
        except Exception:
            logger.exception("Unexpected error while editing an event")
            await _send_ephemeral(
                interaction, "Maaf, terjadi kesalahan. Coba lagi."
            )


class ConfirmDeleteView(discord.ui.View):
    """Ephemeral confirmation before deleting an event."""

    def __init__(self, cog: EventCog, event_id: str) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.event_id = event_id

    @discord.ui.button(
        label="Ya, hapus",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        try:
            await interaction.response.defer()

            async with self.cog.event_lock(self.event_id):
                event = await self.cog.store.delete(self.event_id)
                if event is None:
                    await interaction.edit_original_response(
                        content="Event sudah tidak ada.", view=None
                    )
                    return

                channel = self.cog.bot.get_channel(event.channel_id)
                if channel is None:
                    try:
                        channel = await self.cog.bot.fetch_channel(
                            event.channel_id
                        )
                    except discord.HTTPException:
                        logger.exception(
                            "Failed to fetch the event channel %s",
                            event.channel_id,
                        )

                if (
                    isinstance(channel, discord.abc.Messageable)
                    and event.message_id
                ):
                    try:
                        message = await channel.fetch_message(event.message_id)
                        await message.delete()
                    except discord.NotFound:
                        pass
                    except discord.HTTPException:
                        logger.exception("Failed to delete the event message")

            await interaction.edit_original_response(
                content=(
                    "Event "
                    f"**{discord.utils.escape_markdown(event.title)}** dihapus."
                ),
                view=None,
            )
            self.cog.forget_event(self.event_id)
        except BotmintonError as exc:
            await interaction.edit_original_response(
                content=_user_error(exc),
                view=None,
            )
        except Exception:
            logger.exception("Failed to delete an event")
            await interaction.edit_original_response(
                content="Gagal menghapus event. Coba lagi.",
                view=None,
            )

    @discord.ui.button(
        label="Batal",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(
            content="Penghapusan dibatalkan.", view=None
        )
