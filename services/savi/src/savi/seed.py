"""Synthetic routine generator (docs/05-savi-ia.md §2).

Every event is marked synthetic. The same seed and end date always give the same history.
Routine parameters live here, never in the detectors.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .catalog import DEVICES, DEVICES_BY_ID, DOOR, MOTION_BY_ROOM, OCCUPANCY, OFF, ON, RESIDENTS
from .detectors.timeline import Interval, intersect, subtract
from .store import Event

TV, PC, STUDY_LIGHT = "switch.tv_sala", "switch.pc_estudio", "light.luz_estudio"
KITCHEN_LIGHT, LIVING_LIGHT = "light.luz_cocina", "light.luz_sala"
BED_LIGHT, ROOM2_LIGHT = "light.luz_habitacion_principal", "light.luz_habitacion_2"
FAN = "switch.ventilador_habitacion_principal"


@dataclass(frozen=True)
class Routine:
    # (mean minute of day, ± minutes, uniform)
    r1_leave: tuple[int, int] = (7 * 60 + 10, 10)
    r1_return: tuple[int, int] = (18 * 60 + 30, 40)
    r2_leave: tuple[int, int] = (7 * 60 + 40, 15)
    r2_return: tuple[int, int] = (17 * 60 + 45, 30)
    weekend_outings: tuple[int, int] = (1, 2)
    weekend_outing_hours: tuple[float, float] = (1.0, 4.0)
    # Left ON when the last person leaves.
    leftover_p: dict[str, float] = field(
        default_factory=lambda: {TV: 0.7, PC: 0.6, STUDY_LIGHT: 0.3}
    )
    # About one forgotten-light episode every 2 days: exactly one per 2-day block.
    forgotten_light: str = KITCHEN_LIGHT
    forgotten_light_minutes: tuple[int, int] = (25, 70)
    pc_overnight_p: float = 0.35
    iron_forgotten_p: float = 0.0  # shown live as a safety rule
    occupancy_delay_off_s: int = 300  # delay_off of casa_ocupada in normal use
    motion_gap_min: tuple[float, float] = (2.0, 8.0)
    motion_pulse_s: int = 30
    door_pulse_s: int = 5


ROUTINE = Routine()


class _Builder:
    def __init__(self, seed: int, tz) -> None:
        self.seed = seed
        self.tz = tz
        self.on: dict[str, list[Interval]] = defaultdict(list)
        self.activity: list[tuple[str, float, float, tuple]] = []  # room, start, end, rng key
        self.away: dict[str, list[Interval]] = defaultdict(list)

    def rng(self, *key: object) -> random.Random:
        # String seeds are hashed with SHA-512 by `random`, so this is stable across runs.
        return random.Random(f"{self.seed}:" + ":".join(map(str, key)))

    def at(self, day: date, minute: float) -> float:
        return datetime.combine(day, time(0), self.tz).timestamp() + minute * 60

    def use(
        self,
        entity: str,
        start: float,
        end: float,
        active_until: float | None = None,
        key: tuple = (),
    ) -> None:
        """Device ON in [start, end); someone moves in its room until ``active_until``."""
        self.on[entity].append((start, end))
        room = DEVICES_BY_ID[entity].room
        self.activity.append((room, start, end if active_until is None else active_until, key))
        self.activity.append((room, end, end, key + ("off",)))  # whoever turns it off moves


def _jitter(r: random.Random, spec: tuple[int, int]) -> float:
    mean, spread = spec
    return mean + r.uniform(-spread, spread)


def _union(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _weekday(b: _Builder, i: int, day: date, rt: Routine) -> tuple[float, float]:
    r = b.rng(i, "presence")
    r1_out, r2_out = b.at(day, _jitter(r, rt.r1_leave)), b.at(day, _jitter(r, rt.r2_leave))
    r1_back, r2_back = b.at(day, _jitter(r, rt.r1_return)), b.at(day, _jitter(r, rt.r2_return))
    b.away[RESIDENTS[0]].append((r1_out, r1_back))
    b.away[RESIDENTS[1]].append((r2_out, r2_back))
    last_out, first_back = max(r1_out, r2_out), min(r1_back, r2_back)

    # Working mornings: kitchen, TV and PC on between 6:00 and leaving.
    m = b.rng(i, "morning")
    b.use(
        KITCHEN_LIGHT,
        b.at(day, 360 + m.uniform(0, 10)),
        last_out - m.uniform(5, 15) * 60,
        key=(i, "m", "k"),
    )
    starts = {TV: 360 + m.uniform(5, 20), PC: 360 + m.uniform(10, 30)}
    starts[STUDY_LIGHT] = starts[PC]
    _departure(b, i, "w", starts, day, last_out, first_back, rt)
    return last_out, first_back


def _departure(
    b: _Builder,
    i: int,
    tag: str,
    starts: dict[str, float],
    day: date,
    last_out: float,
    first_back: float,
    rt: Routine,
) -> None:
    for entity, p in rt.leftover_p.items():
        r = b.rng(i, tag, "leftover", entity)
        start = b.at(day, starts[entity])
        if r.random() < p:
            end = first_back + r.uniform(2, 10) * 60
        else:
            end = last_out - r.uniform(2, 15) * 60
        b.use(entity, start, end, key=(i, tag, entity))


def _weekend(b: _Builder, i: int, day: date, rt: Routine) -> None:
    r = b.rng(i, "weekend")
    b.use(
        KITCHEN_LIGHT,
        b.at(day, 480 + r.uniform(0, 30)),
        b.at(day, 540 + r.uniform(0, 30)),
        key=(i, "breakfast"),
    )
    n = r.randint(*rt.weekend_outings)
    start_min = 570 + r.uniform(0, 150)
    for k in range(n):
        hours = r.uniform(*rt.weekend_outing_hours)
        end_min = min(start_min + hours * 60, 18 * 60)
        if end_min - start_min < 60:
            break
        dep, ret = b.at(day, start_min), b.at(day, end_min)
        r2_dep, r2_ret = dep + r.uniform(0, 3) * 60, ret + r.uniform(0, 5) * 60
        b.away[RESIDENTS[0]].append((dep, ret))
        b.away[RESIDENTS[1]].append((r2_dep, r2_ret))
        before = {e: (r2_dep - b.at(day, 0)) / 60 - r.uniform(30, 90) for e in rt.leftover_p}
        _departure(b, i, f"o{k}", before, day, r2_dep, ret, rt)
        start_min = end_min + r.uniform(60, 120)


def _evening(
    b: _Builder,
    i: int,
    day: date,
    last_day: bool,
    next_is_weekday: bool,
    forgotten: bool,
    rt: Routine,
) -> None:
    r = b.rng(i, "evening")
    cook_on = b.at(day, 18 * 60 + 30 + r.uniform(0, 30))
    cook_off = cook_on + r.uniform(45, 75) * 60
    if forgotten:
        extra = b.rng(i, "forgotten").uniform(*rt.forgotten_light_minutes) * 60
        b.use(rt.forgotten_light, cook_on, cook_off + extra, active_until=cook_off, key=(i, "cook"))
    else:
        b.use(KITCHEN_LIGHT, cook_on, cook_off, key=(i, "cook"))

    tv_on = b.at(day, 19 * 60 + r.uniform(0, 30))
    tv_off = b.at(day, 21 * 60 + 30 + r.uniform(0, 45))
    b.use(TV, tv_on, tv_off, key=(i, "tv"))
    b.use(LIVING_LIGHT, tv_on, tv_off, key=(i, "sala"))

    bed_on = b.at(day, 22 * 60 + r.uniform(0, 30))
    b.use(BED_LIGHT, bed_on, bed_on + r.uniform(20, 40) * 60, key=(i, "bed"))
    if r.random() < 0.5:
        r2_on = b.at(day, 21 * 60 + r.uniform(0, 30))
        b.use(ROOM2_LIGHT, r2_on, r2_on + r.uniform(15, 40) * 60, key=(i, "room2"))
    fan = r.random() < 0.5
    pc_evening = r.random() < 0.5
    pc_on = b.at(day, 20 * 60 + r.uniform(0, 30))
    pc_off = b.at(day, 22 * 60 + r.uniform(0, 30))
    if last_day:
        fan = False  # nothing may stay on past the end of the history
    elif fan:
        b.on[FAN].append((bed_on, b.at(day + timedelta(days=1), 330 + r.uniform(0, 30))))

    overnight = not last_day and b.rng(i, "pc_overnight").random() < rt.pc_overnight_p
    if overnight:
        wake = (370 + r.uniform(0, 20)) if next_is_weekday else (480 + r.uniform(0, 30))
        b.use(
            PC, pc_on, b.at(day + timedelta(days=1), wake), active_until=pc_off, key=(i, "pc_night")
        )
    elif pc_evening:
        b.use(PC, pc_on, pc_off, key=(i, "pc"))


def _occupancy(b: _Builder, start: float, end: float, rt: Routine) -> tuple[dict, list, list]:
    span = [(start, end)]
    homes = {res: subtract(span, _union(b.away[res])) for res in RESIDENTS}
    empty = intersect(_union(b.away[RESIDENTS[0]]), _union(b.away[RESIDENTS[1]]))
    someone_home = subtract(span, empty)
    occupied_off = [
        (a + rt.occupancy_delay_off_s, z) for a, z in empty if z - a > rt.occupancy_delay_off_s
    ]
    return homes, someone_home, subtract(span, occupied_off)


def generate(days: int, seed: int, end: datetime, rt: Routine = ROUTINE) -> list[Event]:
    """Synthetic events for ``days`` days ending at ``end`` (a local midnight, exclusive)."""
    tz = end.tzinfo
    b = _Builder(seed, tz)
    first_day = end.date() - timedelta(days=days)
    start_ts = datetime.combine(first_day, time(0), tz).timestamp()
    end_ts = end.timestamp()

    for i in range(days):
        day = first_day + timedelta(days=i)
        if day.weekday() < 5:
            _weekday(b, i, day, rt)
        else:
            _weekend(b, i, day, rt)
        # One forgotten-light episode per 2-day block, counted back from the end.
        block = (days - 1 - i) // 2
        forgotten_offset = b.rng(block, "forgotten_day").randint(0, 1)
        forgotten = (days - 1 - i) % 2 == forgotten_offset
        nxt = day + timedelta(days=1)
        _evening(b, i, day, i == days - 1, nxt.weekday() < 5, forgotten, rt)

    homes, someone_home, occupied = _occupancy(b, start_ts, end_ts, rt)

    raw: list[tuple[float, str, str]] = []

    def emit(entity: str, intervals: list[Interval]) -> None:
        for a, z in intervals:
            if a < end_ts:
                raw.append((a, entity, ON))
            if z < end_ts:
                raw.append((z, entity, OFF))

    for entity in {d.entity_id for d in DEVICES}:
        emit(entity, _union([iv for iv in b.on.get(entity, []) if iv[1] > iv[0]]))

    pulses: dict[str, list[Interval]] = defaultdict(list)
    for room, a, z, key in b.activity:
        r = b.rng("motion", *key)
        t = a
        times = [a] if a == z else []
        while t < z:
            times.append(t)
            t += r.uniform(*rt.motion_gap_min) * 60
        if a != z:
            times.append(z)
        for t in times:
            if start_ts <= t < end_ts and any(h0 <= t < h1 for h0, h1 in someone_home):
                pulses[room].append((t, t + rt.motion_pulse_s))
    for room, entity in MOTION_BY_ROOM.items():
        emit(entity, _union(pulses[room]))

    door: list[Interval] = []
    for res in RESIDENTS:
        emit(res, homes[res])
        for a, z in _union(b.away[res]):
            door += [(a, a + rt.door_pulse_s), (z, z + rt.door_pulse_s)]
    emit(DOOR, _union(door))
    emit(OCCUPANCY, occupied)

    # Initial state at the start of the history, then transitions in time order.
    initial = {d.entity_id: OFF for d in DEVICES}
    initial.update({e: OFF for e in MOTION_BY_ROOM.values()})
    initial.update({DOOR: OFF, OCCUPANCY: ON, RESIDENTS[0]: ON, RESIDENTS[1]: ON})
    state: dict[str, str | None] = {}
    events: list[Event] = []
    for entity, s in sorted(initial.items()):
        events.append(Event(start_ts, entity, None, s, synthetic=True))
        state[entity] = s
    for ts, entity, s in sorted(raw, key=lambda x: (x[0], x[1], x[2] == ON)):
        ts = max(ts, start_ts)
        if state.get(entity) == s:
            continue
        events.append(Event(round(ts, 1), entity, state.get(entity), s, synthetic=True))
        state[entity] = s
    return events
