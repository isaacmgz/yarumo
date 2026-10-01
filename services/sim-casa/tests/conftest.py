from __future__ import annotations

import random
from datetime import datetime

import pytest

from sim_casa.house import House


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, bool]] = []

    def publish(self, topic: str, payload: str, retain: bool = True) -> None:
        self.messages.append((topic, payload, retain))

    def last(self, topic: str) -> str | None:
        for t, p, _ in reversed(self.messages):
            if t == topic:
                return p
        return None

    def payloads(self, topic: str) -> list[str]:
        return [p for t, p, _ in self.messages if t == topic]


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def pub() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_house(pub, clock):
    def _make(store=None, rng=None, motion_probability=1.0, motion_check_s=15.0) -> House:
        return House(
            publisher=pub,
            store=store,
            clock=clock,
            wall_clock=lambda: datetime(2026, 9, 30, 14, 0),
            rng=rng or random.Random(42),
            motion_probability=motion_probability,
            motion_check_s=motion_check_s,
        )

    return _make


def run_for(house: House, clock: FakeClock, seconds: int) -> None:
    for _ in range(seconds):
        clock.advance(1)
        house.tick()
