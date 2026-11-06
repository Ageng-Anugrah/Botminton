"""JSON-backed persistence for badminton events.

The store is intentionally small and exposes a single ``mutate`` entry point so
it can be replaced by a database repository later without touching the cog.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from botminton.errors import EventNotFoundError, StoreError
from botminton.models import Event

T = TypeVar("T")

_SCHEMA_VERSION = 1


class EventStore:
    """A single-process JSON event store with atomic writes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._events: dict[str, Event] = {}

    @property
    def path(self) -> Path:
        return self._path

    async def load(self) -> None:
        """Load events from disk, creating an empty store when absent."""
        async with self._lock:
            if not self._path.exists():
                self._events = {}
                return

            try:
                raw = await asyncio.to_thread(
                    self._path.read_text, encoding="utf-8"
                )
            except OSError as exc:
                raise StoreError(
                    f"Gagal membaca file data {self._path}: {exc}"
                ) from exc

            if not raw.strip():
                self._events = {}
                return

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StoreError(
                    f"File data {self._path} bukan JSON yang valid: {exc}"
                ) from exc

            if not isinstance(payload, dict):
                raise StoreError(f"Format file data {self._path} tidak valid.")

            version = payload.get("version", _SCHEMA_VERSION)
            if version != _SCHEMA_VERSION:
                raise StoreError(
                    f"Versi file data {self._path} tidak didukung: {version}."
                )

            raw_events = payload.get("events", {})
            if not isinstance(raw_events, dict):
                raise StoreError(f"Format daftar event di {self._path} tidak valid.")

            try:
                events = {
                    str(event_id): Event.from_dict(event_data)
                    for event_id, event_data in raw_events.items()
                }
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise StoreError(
                    f"Format data event di {self._path} tidak valid: {exc}"
                ) from exc

            self._events = events

    async def create(self, event: Event) -> Event:
        async with self._lock:
            if event.id in self._events:
                raise StoreError(f"Event dengan id {event.id} sudah ada.")

            stored = copy.deepcopy(event)
            updated = {**self._events, stored.id: stored}
            await self._write(updated)
            self._events = updated
            return copy.deepcopy(stored)

    async def get(self, event_id: str) -> Event | None:
        async with self._lock:
            event = self._events.get(event_id)
            return copy.deepcopy(event) if event is not None else None

    async def list_all(self) -> list[Event]:
        async with self._lock:
            return [copy.deepcopy(event) for event in self._events.values()]

    async def mutate(self, event_id: str, callback: Callable[[Event], T]) -> T:
        """Apply ``callback`` to a draft event and persist it on success.

        If the callback raises, the in-memory event and the file are left
        untouched.
        """
        async with self._lock:
            current = self._events.get(event_id)
            if current is None:
                raise EventNotFoundError(event_id)

            draft = copy.deepcopy(current)
            result = callback(draft)

            updated = {**self._events, event_id: draft}
            await self._write(updated)
            self._events = updated
            return result

    async def delete(self, event_id: str) -> Event | None:
        async with self._lock:
            event = self._events.get(event_id)
            if event is None:
                return None

            updated = {
                key: value
                for key, value in self._events.items()
                if key != event_id
            }
            await self._write(updated)
            self._events = updated
            return copy.deepcopy(event)

    async def _write(self, events: dict[str, Event]) -> None:
        payload = {
            "version": _SCHEMA_VERSION,
            "events": {
                event_id: event.to_dict() for event_id, event in events.items()
            },
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)

        try:
            await asyncio.to_thread(self._write_atomic, text)
        except OSError as exc:
            raise StoreError(
                f"Gagal menyimpan file data {self._path}: {exc}"
            ) from exc

    def _write_atomic(self, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_name(f"{self._path.name}.tmp")

        try:
            temp_path.write_text(text, encoding="utf-8")
            os.replace(temp_path, self._path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
