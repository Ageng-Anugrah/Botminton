"""Async client for the ayo.co.id venue availability API."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import aiohttp

from botminton.errors import AyoAPIError
from botminton.services.availability import (
    Availability,
    TimeSlot,
    build_slot,
    merge_slots,
)
from botminton.venues import Venue

logger = logging.getLogger(__name__)

API_URL = "https://ayo.co.id/venues-ajax/op-times-and-fields"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# The endpoint rejects non-browser user agents with "Akses ditolak.",
# so a regular browser identity is required.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


class AyoClient:
    """Thin async wrapper around the ayo.co.id availability endpoint."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def get_availability(self, venue: Venue, target_date: date) -> Availability:
        """Fetch and parse availability for ``venue`` on ``target_date``."""
        params = {"venue_id": venue.ayo_id, "date": target_date.isoformat()}

        try:
            async with self._session.get(
                API_URL,
                params=params,
                headers=_HEADERS,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except asyncio.TimeoutError as exc:
            raise AyoAPIError("ayo.co.id did not respond in time") from exc
        except aiohttp.ClientResponseError as exc:
            raise AyoAPIError(f"ayo.co.id returned HTTP {exc.status}") from exc
        except aiohttp.ClientError as exc:
            raise AyoAPIError("could not reach ayo.co.id") from exc
        except ValueError as exc:
            raise AyoAPIError("ayo.co.id returned invalid JSON") from exc

        return parse_availability(payload, target_date)


def parse_availability(payload: Any, target_date: date) -> Availability:
    """Convert a raw API payload into an :class:`Availability` value."""
    if not isinstance(payload, dict):
        raise AyoAPIError("ayo.co.id returned an unexpected payload")

    op_time = payload.get("op_time")
    if not isinstance(op_time, dict):
        raise AyoAPIError("ayo.co.id response is missing operating hours")

    day = op_time.get("day")
    if not isinstance(day, str) or not day.strip():
        day = target_date.strftime("%A")

    hours = op_time.get("hours")
    is_open = isinstance(hours, (list, dict)) and len(hours) > 0

    slots: set[TimeSlot] = set()
    if is_open:
        fields = payload.get("fields", [])
        if not isinstance(fields, list):
            raise AyoAPIError("ayo.co.id response has an invalid fields list")

        for field in fields:
            if not isinstance(field, dict):
                continue

            field_slots = field.get("slots", [])
            if not isinstance(field_slots, list):
                continue

            for slot in field_slots:
                if not isinstance(slot, dict) or not slot.get("is_available"):
                    continue

                try:
                    slots.add(build_slot(slot["start_time"], slot["end_time"]))
                except (KeyError, TypeError, ValueError):
                    logger.warning("Skipping malformed availability slot: %r", slot)

    return Availability(
        day=day.strip(),
        target_date=target_date,
        is_open=is_open,
        slots=tuple(merge_slots(slots)),
    )
