"""Discord bot definition and lifecycle management."""

from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands

from botminton.cogs.event import EventCog
from botminton.cogs.schedule import ScheduleCog
from botminton.config import Settings
from botminton.services.ayo import AyoClient
from botminton.services.event_store import EventStore

logger = logging.getLogger(__name__)


class BotmintonBot(commands.Bot):
    """Bot that owns shared resources and one-time command syncing."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.settings = settings
        self.session: aiohttp.ClientSession | None = None
        self.event_store: EventStore | None = None

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()
        self.event_store = EventStore(self.settings.events_file)
        await self.event_store.load()

        await self.add_cog(ScheduleCog(self, AyoClient(self.session)))
        await self.add_cog(
            EventCog(self, self.event_store, self.settings.timezone)
        )
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        try:
            if self.settings.guild_id is not None:
                guild = discord.Object(id=self.settings.guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logger.info(
                    "Synced %d command(s) to guild %s",
                    len(synced),
                    self.settings.guild_id,
                )
            else:
                synced = await self.tree.sync()
                logger.info("Synced %d global command(s)", len(synced))
        except discord.HTTPException:
            logger.exception("Failed to sync application commands")

    async def on_ready(self) -> None:
        if self.user is not None:
            logger.info("Logged in as %s (id=%s)", self.user, self.user.id)

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()
        await super().close()
