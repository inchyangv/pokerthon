"""Bot seeding logic — creates default bots on server startup."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.account import Account
from app.models.table import SeatStatus, TableSeat

logger = logging.getLogger(__name__)

# Default bots: (nickname, bot_type, initial_table_no)
_DEFAULT_BOTS = [
    ("bot_tag_1", "TAG", 1),
    ("bot_lag_1", "LAG", 1),
    ("bot_fish_1", "FISH", 1),
    ("bot_tag_2", "TAG", 2),
    ("bot_lag_2", "LAG", 2),
    ("bot_fish_2", "FISH", 2),
]


async def seed_bots(session: AsyncSession) -> None:
    """Create default bots and seat them. Skip already-existing bots."""
    if not settings.BOT_AUTO_SEED:
        return

    logger.info("BOT_AUTO_SEED=True — starting bot seed")

    for nickname, bot_type, table_no in _DEFAULT_BOTS:
        try:
            await _seed_one_bot(session, nickname, bot_type, table_no)
        except Exception:
            logger.exception("Failed to seed bot %s — continuing", nickname)


async def _seed_one_bot(
    session: AsyncSession, nickname: str, bot_type: str, table_no: int
) -> None:
    from app.services.bot_service import create_bot
    from app.services.seat_service import sit
    from app.services.table_service import create_table

    # Check if bot already exists
    existing = (
        await session.execute(select(Account).where(Account.nickname == nickname))
    ).scalar_one_or_none()

    if existing:
        logger.info("Bot %s already exists — skipping creation", nickname)
        account_id = existing.id
    else:
        result = await create_bot(session, bot_type, nickname)
        account_id = result["account_id"]
        logger.info("Created bot %s (%s)", nickname, bot_type)

    # Ensure target table exists
    from app.models.table import Table
    table = (
        await session.execute(select(Table).where(Table.table_no == table_no))
    ).scalar_one_or_none()

    if not table:
        table = await create_table(session, table_no)
        logger.info("Created table %d for seeding", table_no)

    # Check if already seated
    seat = (
        await session.execute(
            select(TableSeat).where(
                TableSeat.account_id == account_id,
                TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
            )
        )
    ).scalar_one_or_none()

    if seat:
        logger.info("Bot %s already seated — skipping", nickname)
        return

    # Seat the bot
    try:
        await sit(session, account_id, table_no, seat_no=None)
        logger.info("Bot %s seated at table %d", nickname, table_no)
    except Exception as e:
        logger.warning("Could not seat bot %s: %s", nickname, e)
