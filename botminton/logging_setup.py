"""Logging configuration for the bot process."""

from __future__ import annotations

import logging

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str) -> None:
    """Configure root logging once, at process startup."""
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
