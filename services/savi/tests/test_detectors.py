"""Detectors D1–D3 and R1 (docs/05-savi-ia.md §3 and §9)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest

from savi.catalog import IRON, MOTION_BY_ROOM, OCCUPANCY
from savi.detectors import run_all
from savi.seed import generate
from savi.store import Store

from .conftest import END, TZ

TV, PC = "switch.tv_sala", "switch.pc_estudio"
KITCHEN = "light.luz_cocina"


@pytest.mark.parametrize("shift", range(7))
def test_seed_42_gives_exactly_the_expected_suggestions(shift):
    """D1 is exactly TV + PC, at least one D2 and one D3, and the iron only appears in R1.

    Checked for every weekday alignment of the end date, so the demo works any day.
    """
    end = END + timedelta(days=shift)
    store = Store(":memory:")
    store.add_events(generate(21, 42, end))
    proposals = run_all(store, end.timestamp(), TZ)

    by_detector = Counter(p.detector for p in proposals)
    assert by_detector["olvido_al_salir"] == 1
    assert by_detector["luz_sin_movimiento"] >= 1
    assert by_detector["consumo_nocturno"] >= 1
    assert by_detector["plancha_olvidada"] == 1
    assert set(by_detector) == {
        "olvido_al_salir",
        "luz_sin_movimiento",
        "consumo_nocturno",
        "plancha_olvidada",
    }

    d1 = next(p for p in proposals if p.detector == "olvido_al_salir")
    assert d1.entities == [PC, TV]
    for p in proposals:
        if p.detector != "plancha_olvidada":
            assert IRON not in p.entities
            assert p.evidence["datos_simulados"] is True
            assert p.est_kwh_month is not None and p.est_kwh_month > 0
            assert p.evidence["formula"] and p.evidence["calculo"]


def _departures(sc, days, left_on):
    """One departure per day at 08:00, back at 18:00; ``left_on[d]`` devices stay ON."""
    sc.set(sc.at(0, "00:00"), OCCUPANCY, "on")
    for d in range(days):
        for dev in left_on[d]:
            sc.set(sc.at(d, "07:00"), dev, "on")
        sc.set(sc.at(d, "08:00"), OCCUPANCY, "off")
        sc.set(sc.at(d, "18:00"), OCCUPANCY, "on")
        for dev in left_on[d]:
            sc.set(sc.at(d, "18:05"), dev, "off")
    sc.save()


def test_d1_frequency_threshold_grouping_and_formula(scenario, store):
    left = [[TV, PC], [TV], [TV, PC], [TV], [TV], []]  # TV 5/6, PC 2/6
    _departures(scenario, 6, left)
    now = scenario.at(6, "00:00")
    [d1] = [p for p in run_all(store, now, TZ) if p.detector == "olvido_al_salir"]

    assert d1.entities == [TV]  # PC 2/6 < 0.5 stays out
    assert d1.confidence == "alta"  # 5/6 >= 0.75
    ev = d1.evidence
    assert ev["salidas"] == 6 and ev["mediana_horas_ausencia"] == 10
    # By hand: 90 W × 5/6 × 10 h × (6 × 30/14 = 12.857) / 1000 = 9.643 kWh/month
    assert d1.est_kwh_month == pytest.approx(round(90 * 5 / 6 * 10 * (6 * 30 / 14) / 1000, 2))
    assert d1.est_kwh_month == 9.64


def test_d1_medium_confidence_and_minimum_departures(scenario, store):
    _departures(scenario, 4, [[TV]] * 4)
    assert not [
        p for p in run_all(store, scenario.at(4, "00:00"), TZ) if p.detector == "olvido_al_salir"
    ]

    store.delete_synthetic_events()
    _departures(scenario, 6, [[TV], [TV], [TV], [TV], [], []])  # 4/6 = 0.67
    [d1] = [
        p for p in run_all(store, scenario.at(6, "00:00"), TZ) if p.detector == "olvido_al_salir"
    ]
    assert d1.confidence == "media"


def _light_episodes(sc, days, quiet_min, motion_every=None):
    """Kitchen light ON 20:00 for ``quiet_min`` minutes with the house occupied."""
    motion = MOTION_BY_ROOM["cocina"]
    sc.set(sc.at(0, "00:00"), OCCUPANCY, "on")
    sc.set(sc.at(0, "00:00"), motion, "off")
    for d in range(days):
        start = sc.at(d, "20:00")
        sc.set(start - 30, motion, "on")
        sc.set(start, motion, "off")
        sc.set(start, KITCHEN, "on")
        if motion_every:
            t = start + motion_every * 60
            while t < start + quiet_min * 60:
                sc.set(t, motion, "on")
                sc.set(t + 30, motion, "off")
                t += motion_every * 60
        sc.set(start + quiet_min * 60, KITCHEN, "off")
    sc.save()


def test_d2_needs_six_episodes_of_twenty_minutes(scenario, store):
    _light_episodes(scenario, 6, quiet_min=50)
    [d2] = [
        p for p in run_all(store, scenario.at(7, "00:00"), TZ) if p.detector == "luz_sin_movimiento"
    ]
    assert d2.entities == [KITCHEN] and d2.evidence["episodios"] == 6
    # By hand: 9 W × (50 − 20) min = 0.5 h × (6 × 30/14) / 1000 = 0.0579 kWh/month (it is small)
    assert d2.est_kwh_month == pytest.approx(0.058, abs=1e-3)


def test_d2_ignores_five_episodes_and_lights_with_motion(scenario, store):
    _light_episodes(scenario, 5, quiet_min=50)
    assert not [
        p for p in run_all(store, scenario.at(6, "00:00"), TZ) if p.detector == "luz_sin_movimiento"
    ]
    store.delete_synthetic_events()
    _light_episodes(scenario, 10, quiet_min=90, motion_every=10)
    assert not [
        p
        for p in run_all(store, scenario.at(11, "00:00"), TZ)
        if p.detector == "luz_sin_movimiento"
    ]


def _pc_nights(sc, nights, motion_every=None):
    motion = MOTION_BY_ROOM["estudio"]
    sc.set(sc.at(0, "00:00"), motion, "off")
    for d in range(nights):
        sc.set(sc.at(d, "22:00"), PC, "on")
        if motion_every:
            t = sc.at(d, "22:00")
            while t < sc.at(d + 1, "06:00"):
                sc.set(t, motion, "on")
                sc.set(t + 30, motion, "off")
                t += motion_every * 60
        sc.set(sc.at(d + 1, "06:00"), PC, "off")
    sc.save()


def test_d3_needs_four_nights(scenario, store):
    _pc_nights(scenario, 4)
    [d3] = [
        p for p in run_all(store, scenario.at(6, "00:00"), TZ) if p.detector == "consumo_nocturno"
    ]
    assert d3.entities == [PC] and d3.evidence["noches"] == 4
    # From 01:00 to 05:00 = 4 h. By hand: 150 W × 4 h × (4 × 30/14) / 1000 = 5.143 kWh/month
    assert d3.evidence["mediana_horas_evitables"] == 4
    assert d3.est_kwh_month == pytest.approx(5.143, abs=1e-3)


def test_d3_ignores_three_nights_and_nights_with_motion(scenario, store):
    _pc_nights(scenario, 3)
    assert not [
        p for p in run_all(store, scenario.at(6, "00:00"), TZ) if p.detector == "consumo_nocturno"
    ]
    store.delete_synthetic_events()
    _pc_nights(scenario, 6, motion_every=15)
    assert not [
        p for p in run_all(store, scenario.at(8, "00:00"), TZ) if p.detector == "consumo_nocturno"
    ]


def test_r1_is_offered_from_day_one(store):
    [r1] = run_all(store, END.timestamp(), TZ)
    assert r1.detector == "plancha_olvidada" and r1.entities == [IRON]
    assert r1.est_kwh_month is None and r1.confidence == "alta"
    assert "de fábrica" in r1.explanation
