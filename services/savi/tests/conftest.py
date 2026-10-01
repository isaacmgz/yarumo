from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from savi.seed import generate
from savi.store import Event, Store

TZ = ZoneInfo("America/Bogota")
END = datetime(2026, 9, 30, 0, 0, tzinfo=TZ)  # a Wednesday midnight


@pytest.fixture
def store() -> Store:
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture(scope="session")
def seeded_events() -> list[Event]:
    return generate(21, 42, END)


class Scenario:
    """Builds hand-made histories: ``at(day, "HH:MM")`` -> epoch seconds."""

    def __init__(self, store: Store, base: datetime) -> None:
        self.store = store
        self.base = base
        self.events: list[Event] = []

    def at(self, day: int, hhmm: str) -> float:
        h, m = map(int, hhmm.split(":"))
        return self.base.timestamp() + day * 86400 + h * 3600 + m * 60

    def set(self, ts: float, entity_id: str, state: str) -> None:
        self.events.append(Event(ts, entity_id, None, state, synthetic=True))

    def save(self) -> None:
        self.store.add_events(sorted(self.events, key=lambda e: e.ts))
        self.events = []


@pytest.fixture
def scenario(store) -> Scenario:
    return Scenario(store, datetime(2026, 9, 1, 0, 0, tzinfo=TZ))
