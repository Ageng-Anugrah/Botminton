"""Application entrypoint."""

from __future__ import annotations

import logging

from botminton.bot import BotmintonBot
from botminton.config import Settings
from botminton.errors import ConfigError
from botminton.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    configure_logging(settings.log_level)
    logger.info("Starting Botminton")

    bot = BotmintonBot(settings)
    bot.run(settings.token, log_handler=None)
