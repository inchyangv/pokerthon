"""Pydantic schemas for hand history and action log APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HandSummary(BaseModel):
    hand_id: int
    hand_no: int
    started_at: datetime
    finished_at: datetime | None
    board: list[str]
    winners: list[int]  # seat numbers
    pot_summary: dict[str, Any]


class PlayerInHand(BaseModel):
    seat_no: int
    nickname: str | None
    starting_stack: int
    ending_stack: int
    folded: bool
    hole_cards: list[str] | None  # None = not revealed


class HandDetail(BaseModel):
    hand_id: int
    hand_no: int
    table_no: int
    started_at: datetime
    finished_at: datetime | None
    board: list[str]
    players: list[PlayerInHand]
    pot_summary: dict[str, Any]
    winners: list[int]


class ActionLog(BaseModel):
    seq: int
    street: str | None
    actor_seat: int | None
    actor_nickname: str | None
    action_type: str
    amount: int | None
    amount_to: int | None
    is_system_action: bool
    timestamp: datetime


class PaginatedResponse(BaseModel):
    items: list[Any]
    next_cursor: int | None
    has_more: bool
