"""Synthetic routine (docs/05-savi-ia.md §2)."""

from __future__ import annotations

from datetime import timedelta

from savi.catalog import IRON, is_power_sensor, is_tracked
from savi.seed import generate

from .conftest import END


def test_same_seed_same_history(seeded_events):
    assert generate(21, 42, END) == seeded_events
    assert generate(21, 7, END) != seeded_events


def test_history_is_synthetic_and_covers_21_days_ending_at_midnight(seeded_events):
    assert seeded_events and all(e.synthetic for e in seeded_events)
    start = (END - timedelta(days=21)).timestamp()
    assert min(e.ts for e in seeded_events) == start
    assert max(e.ts for e in seeded_events) < END.timestamp()


def test_events_are_tracked_transitions_and_the_iron_never_turns_on(seeded_events):
    for e in seeded_events:
        assert is_tracked(e.entity_id) and not is_power_sensor(e.entity_id)
        assert e.old_state != e.new_state
        assert not (e.entity_id == IRON and e.new_state == "on")


def test_nothing_is_left_on_at_the_end(seeded_events):
    last = {}
    for e in seeded_events:
        last[e.entity_id] = e.new_state
    assert last["binary_sensor.casa_ocupada"] == "on"
    assert all(s == "off" for k, s in last.items() if k.startswith(("light.", "switch.")))
