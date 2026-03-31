"""Table snapshot management and long-poll event notification."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hand import TableSnapshot

# Per-table asyncio.Event for long-poll notification
_table_events: dict[int, asyncio.Event] = {}

# Global event: fires whenever ANY table's state changes (for lobby SSE)
_lobby_event: asyncio.Event = asyncio.Event()


def get_lobby_event() -> asyncio.Event:
    return _lobby_event


async def wait_for_lobby_change(wait_ms: int) -> bool:
    """Wait up to wait_ms milliseconds for any table state change."""
    global _lobby_event
    ev = _lobby_event
    try:
        await asyncio.wait_for(ev.wait(), timeout=wait_ms / 1000)
        return True
    except asyncio.TimeoutError:
        return False


def get_table_event(table_id: int) -> asyncio.Event:
    if table_id not in _table_events:
        _table_events[table_id] = asyncio.Event()
    return _table_events[table_id]


async def bump_snapshot(session: AsyncSession, table_id: int, snapshot_data: dict | None = None) -> int:
    """Increment snapshot version, persist, and notify long-poll waiters.

    Returns the new version number.
    """
    import json

    snap = await session.get(TableSnapshot, table_id)
    if snap is None:
        snap = TableSnapshot(
            table_id=table_id,
            version=1,
            snapshot_json=json.dumps(snapshot_data or {}),
        )
        session.add(snap)
        new_version = 1
    else:
        snap.version += 1
        if snapshot_data is not None:
            snap.snapshot_json = json.dumps(snapshot_data)
        snap.updated_at = datetime.now(timezone.utc)
        new_version = snap.version

    await session.flush()

    # Notify per-table long-poll waiters
    event = get_table_event(table_id)
    event.set()
    _table_events[table_id] = asyncio.Event()

    # Notify lobby SSE waiters
    global _lobby_event
    _lobby_event.set()
    _lobby_event = asyncio.Event()

    return new_version


async def get_snapshot_version(session: AsyncSession, table_id: int) -> int:
    snap = await session.get(TableSnapshot, table_id)
    return snap.version if snap else 0


async def wait_for_change(table_id: int, current_version: int, wait_ms: int) -> bool:
    """Wait up to wait_ms milliseconds for a version change.

    Returns True if a change occurred, False on timeout.
    """
    event = get_table_event(table_id)
    try:
        await asyncio.wait_for(event.wait(), timeout=wait_ms / 1000)
        return True
    except asyncio.TimeoutError:
        return False


def fire_table_event(table_id: int) -> None:
    """Notify SSE/long-poll waiters that the table state has changed.

    Call this AFTER session.commit() to avoid serving stale data.
    """
    global _lobby_event
    # Per-table event (for live view SSE)
    event = get_table_event(table_id)
    event.set()
    _table_events[table_id] = asyncio.Event()
    # Global lobby event
    _lobby_event.set()
    _lobby_event = asyncio.Event()
