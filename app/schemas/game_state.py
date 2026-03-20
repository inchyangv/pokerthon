"""Pydantic schemas for game state API responses."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SeatState(BaseModel):
    seat_no: int
    nickname: str | None
    stack: int
    folded: bool
    all_in: bool
    round_contribution: int
    hand_contribution: int
    seat_status: str


class SidePot(BaseModel):
    index: int
    amount: int
    eligible_seats: list[int]


class UncalledReturn(BaseModel):
    seat_no: int
    amount: int


class PotView(BaseModel):
    main_pot: int
    side_pots: list[SidePot]
    uncalled_return: UncalledReturn | None


class PrivateGameState(BaseModel):
    table_no: int
    hand_id: int | None
    street: str | None
    hole_cards: list[str]
    board: list[str]
    seats: list[SeatState]
    button_seat_no: int | None
    action_seat_no: int | None
    current_bet: int
    to_call: int
    legal_actions: list[dict[str, Any]]
    min_raise_to: int | None
    max_raise_to: int | None
    pot_view: PotView
    action_deadline_at: datetime | None
    state_version: int
