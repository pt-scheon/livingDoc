"""Pydantic request models (validation happens at the API boundary)."""
from datetime import date
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    branch: str = Field(min_length=1, max_length=80)


class ItemIn(BaseModel):
    branch: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    sku: Optional[str] = Field(default=None, max_length=64)
    unit: Optional[str] = Field(default=None, max_length=16)
    min_stock: Optional[float] = Field(default=None, ge=0)
    daily_use: Optional[float] = Field(default=None, ge=0)
    shelf_life_days: Optional[int] = Field(default=None, ge=0, le=3650)
    counted: Optional[float] = Field(default=None, ge=0, description="Physical count; records a correction movement")


class ScanBatch(BaseModel):
    """Scanner events are accepted loosely on purpose: one bad event is skipped and flagged, it never rejects the batch.

    Event fields: event_id (idempotency key), sku and/or item, qty (default 1), direction ("in"|"out"),
    branch (optional), ts (optional ISO timestamp).
    """
    branch: Optional[str] = Field(default=None, max_length=80)
    events: List[Any] = Field(min_length=1, max_length=5000)


class FestivalIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    date: date
    surge_multiplier: float = Field(ge=1, le=20)
    supplier_blackout_days: int = Field(ge=0, le=60)


class LeadDaysIn(BaseModel):
    days: int = Field(ge=0, le=90)


class PromisePatch(BaseModel):
    done: bool
