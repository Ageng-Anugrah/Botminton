"""Slash commands for checking badminton court schedules."""

from __future__ import annotations

import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from botminton.errors import AyoAPIError
from botminton.services.availability import (
    render_availability,
    render_full,
    render_not_open,
)
from botminton.services.ayo import AyoClient
from botminton.venues import VENUES, resolve_venue

logger = logging.getLogger(__name__)

_DATE_FORMAT = "%Y-%m-%d"

_PLACE_CHOICES = [
    app_commands.Choice(name=venue.label, value=venue.key)
    for venue in VENUES.values()
]


class ScheduleCog(commands.Cog):
    """Commands related to court availability."""

    def __init__(self, bot: commands.Bot, ayo_client: AyoClient) -> None:
        self.bot = bot
        self.ayo_client = ayo_client

    @app_commands.command(name="jadwal", description="Cek jadwal GOR yang tersedia")
    @app_commands.describe(place="Nama GOR", date="Tanggal dengan format YYYY-MM-DD")
    @app_commands.choices(place=_PLACE_CHOICES)
    async def jadwal(
        self,
        interaction: discord.Interaction,
        place: app_commands.Choice[str],
        date: str,
    ) -> None:
        venue = resolve_venue(place.value)
        if venue is None:
            await interaction.response.send_message(
                "Maaf, baru bisa GOR Kukusan dan Sima Kak 😭😭",
                ephemeral=True,
            )
            return

        try:
            target_date = datetime.strptime(date.strip(), _DATE_FORMAT).date()
        except ValueError:
            await interaction.response.send_message(
                "Format tanggal harus YYYY-MM-DD, contoh: 2026-11-07.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            availability = await self.ayo_client.get_availability(venue, target_date)
        except AyoAPIError:
            logger.exception(
                "Failed to fetch schedule for %s on %s", venue.key, target_date
            )
            await interaction.followup.send(
                "Maaf, layanan jadwal sedang gangguan. "
                "Coba lagi beberapa saat lagi ya Kak 🙏"
            )
            return

        if not availability.is_open:
            message = render_not_open(availability.day, target_date)
        elif not availability.slots:
            message = render_full(availability.day, target_date)
        else:
            message = render_availability(
                venue.label, availability.day, target_date, availability.slots
            )

        await interaction.followup.send(message)

    @app_commands.command(name="hello", description="Sapa bot")
    async def hello(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Hello!")

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        command_name = getattr(interaction.command, "qualified_name", "unknown")
        logger.error(
            "Application command /%s failed", command_name, exc_info=error
        )

        message = "Maaf, terjadi kesalahan saat memproses perintah ini."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
