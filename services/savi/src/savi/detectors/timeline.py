"""State timelines rebuilt from stored events, plus small interval helpers.

All times are epoch seconds. Intervals are half-open ``(start, end)`` tuples, sorted and disjoint.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterable

from ..catalog import ON
from ..store import Event

Interval = tuple[float, float]


class Timeline:
    """State of one entity over time. Before its first event the state is unknown (None)."""

    def __init__(self) -> None:
        self.times: list[float] = []
        self.states: list[str | None] = []
        self.synthetic: list[bool] = []

    def add(self, ts: float, state: str | None, synthetic: bool) -> None:
        self.times.append(ts)
        self.states.append(state)
        self.synthetic.append(synthetic)

    def state_at(self, t: float) -> str | None:
        i = bisect.bisect_right(self.times, t) - 1
        return self.states[i] if i >= 0 else None

    def on_intervals(self, start: float, end: float) -> list[Interval]:
        """Sub-intervals of [start, end) where the state is ``on``."""
        out: list[Interval] = []
        current = self.state_at(start)
        seg_start = start
        i = bisect.bisect_right(self.times, start)
        while i < len(self.times) and self.times[i] < end:
            t, s = self.times[i], self.states[i]
            if (current == ON) != (s == ON):
                if current == ON:
                    out.append((seg_start, t))
                seg_start = t
            current = s
            i += 1
        if current == ON and seg_start < end:
            out.append((seg_start, end))
        return [iv for iv in out if iv[1] > iv[0]]

    def transitions(
        self, start: float, end: float
    ) -> list[tuple[float, str | None, str | None, bool]]:
        """(ts, old, new, synthetic) for every real state change inside [start, end)."""
        out = []
        i = bisect.bisect_left(self.times, start)
        prev = self.states[i - 1] if i > 0 else None
        while i < len(self.times) and self.times[i] < end:
            s = self.states[i]
            if s != prev:
                out.append((self.times[i], prev, s, self.synthetic[i]))
            prev = s
            i += 1
        return out

    def synthetic_in(self, start: float, end: float) -> bool:
        i = bisect.bisect_right(self.times, start) - 1
        j = bisect.bisect_left(self.times, end)
        return any(self.synthetic[max(i, 0) : j]) if self.times else False


def build_timelines(events: Iterable[Event]) -> dict[str, Timeline]:
    timelines: dict[str, Timeline] = defaultdict(Timeline)
    for e in events:
        timelines[e.entity_id].add(e.ts, e.new_state, e.synthetic)
    return timelines


def intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if lo < hi:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(a: list[Interval], b: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for start, end in a:
        cur = start
        for bs, be in b:
            if be <= cur or bs >= end:
                continue
            if bs > cur:
                out.append((cur, bs))
            cur = max(cur, be)
            if cur >= end:
                break
        if cur < end:
            out.append((cur, end))
    return out


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
