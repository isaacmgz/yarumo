"""Shared types for the deterministic detectors (docs/05-savi-ia.md §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

WINDOW_DAYS = 14
DAYS_PER_MONTH = 30


@dataclass(frozen=True)
class Context:
    """What every detector receives: timelines, the analysis instant and the house time zone."""

    timelines: dict
    now: float
    tz: ZoneInfo

    @property
    def window_start(self) -> float:
        return self.now - WINDOW_DAYS * 86400

    def local(self, ts: float) -> datetime:
        return datetime.fromtimestamp(ts, self.tz)


@dataclass
class Proposal:
    detector: str
    title: str
    entities: list[str]
    evidence: dict
    est_kwh_month: float | None
    confidence: str  # "alta" | "media"
    explanation: str
    extra: dict = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return f"{self.detector}:{','.join(sorted(self.entities))}"


def per_month(count_in_window: float) -> float:
    return count_in_window * DAYS_PER_MONTH / WINDOW_DAYS


def kwh(power_w: float, hours: float) -> float:
    return power_w * hours / 1000
