"""Per-table asyncio.Lock registry for serializing concurrent action requests."""
from __future__ import annotations

import asyncio

# Dict[table_no, asyncio.Lock] — safe in a single-threaded asyncio process
_table_locks: dict[int, asyncio.Lock] = {}


def get_table_lock(table_no: int) -> asyncio.Lock:
    """Return the asyncio.Lock for *table_no*, creating it if needed.

    asyncio is single-threaded, so plain dict access is safe without a meta-lock.
    Different tables get independent locks and can process actions in parallel.
    """
    if table_no not in _table_locks:
        _table_locks[table_no] = asyncio.Lock()
    return _table_locks[table_no]
