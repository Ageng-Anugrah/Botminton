"""Environment-based configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from botminton.errors import ConfigError

_VALID_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
_DEFAULT_EVENTS_FILE = "data/events.json"
_DEFAULT_TIMEZONE = "Asia/Jakarta"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from the environment."""

    token: str
    guild_id: int | None
    log_level: str
    events_file: Path
    timezone: ZoneInfo

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token."
            )

        guild_id = _parse_optional_guild_id(os.getenv("GUILD_ID", ""))
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if log_level not in _VALID_LOG_LEVELS:
            valid_levels = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ConfigError(f"LOG_LEVEL must be one of: {valid_levels}.")

        events_file = Path(
            os.getenv("EVENTS_FILE", _DEFAULT_EVENTS_FILE).strip()
            or _DEFAULT_EVENTS_FILE
        ).expanduser()
        timezone = _parse_timezone(
            os.getenv("TIMEZONE", _DEFAULT_TIMEZONE).strip() or _DEFAULT_TIMEZONE
        )

        return cls(
            token=token,
            guild_id=guild_id,
            log_level=log_level,
            events_file=events_file,
            timezone=timezone,
        )


def _parse_optional_guild_id(raw_value: str) -> int | None:
    value = raw_value.strip()
    if not value:
        return None

    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError("GUILD_ID must be a numeric Discord server ID.") from exc


def _parse_timezone(raw_value: str) -> ZoneInfo:
    try:
        return ZoneInfo(raw_value)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"TIMEZONE is not recognised: {raw_value}.") from exc
