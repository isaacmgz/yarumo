"""Contract: commands, energy integration, persistence, occupancy, scenarios."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from sim_casa.house import StateStore, UnknownScenario, medellin_temperature
from tests.conftest import run_for


def test_on_command_sets_state_and_nominal_power_fast(make_house, pub):
    house = make_house()
    start = time.perf_counter()
    house.handle_message("yarumo/casa/tv_sala/set", b"ON")
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0
    assert pub.last("yarumo/casa/tv_sala/estado") == "ON"
    assert pub.last("yarumo/casa/tv_sala/potencia") == "90.0"

    house.handle_message("yarumo/casa/tv_sala/set", b"OFF")
    assert pub.last("yarumo/casa/tv_sala/estado") == "OFF"
    assert pub.last("yarumo/casa/tv_sala/potencia") == "1.0"  # standby


def test_states_are_retained(make_house, pub):
    house = make_house()
    house.set_device("luz_sala", True)
    assert all(retain for _, _, retain in pub.messages)


def test_invalid_commands_are_ignored(make_house, pub):
    house = make_house()
    house.handle_message("yarumo/casa/tv_sala/set", b"MAYBE")
    house.handle_message("yarumo/casa/no_existe/set", b"ON")
    assert pub.messages == []


@pytest.mark.parametrize("device,watts", [("tv_sala", 90), ("plancha_ropa", 1000)])
def test_energy_matches_power_times_time(make_house, clock, device, watts):
    house = make_house()
    before = house.energy_kwh[device]
    house.set_device(device, True)
    run_for(house, clock, 3600)
    gained = house.energy_kwh[device] - before
    expected = watts * 1 / 1000  # kWh in one hour
    assert gained == pytest.approx(expected, rel=0.01)


def test_energy_is_monotonic_and_includes_standby(make_house, clock):
    house = make_house()
    values = []
    for _ in range(10):
        run_for(house, clock, 60)
        values.append(house.energy_kwh["pc_estudio"])
    assert values == sorted(values)
    assert values[-1] == pytest.approx(2 * 600 / 3_600_000, rel=0.01)  # 2 W standby
    assert house.energy_kwh["luz_sala"] == 0.0  # LED has no standby


def test_energy_published_every_30s_with_4_decimals(make_house, clock, pub):
    house = make_house()
    house.set_device("plancha_ropa", True)
    run_for(house, clock, 30)
    assert pub.last("yarumo/casa/plancha_ropa/energia") == "0.0083"
    assert pub.last("yarumo/casa/plancha_ropa/potencia") == "1000.0"


def test_energy_persists_across_restart(make_house, clock, tmp_path):
    path = tmp_path / "state.json"
    house = make_house(store=StateStore(path))
    house.set_device("tv_sala", True)
    run_for(house, clock, 600)
    house.save()
    kwh = house.energy_kwh["tv_sala"]
    assert kwh > 0

    restarted = make_house(store=StateStore(path))
    assert restarted.energy_kwh["tv_sala"] == pytest.approx(kwh)
    assert restarted.on["tv_sala"] is True
    run_for(restarted, clock, 60)
    assert restarted.energy_kwh["tv_sala"] > kwh


def test_corrupt_state_file_does_not_crash(make_house, tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")
    house = make_house(store=StateStore(path))
    assert house.energy_kwh["tv_sala"] == 0.0


def test_no_motion_when_house_empty(make_house, clock, pub):
    house = make_house(motion_probability=1.0)
    house.set_device("tv_sala", True)
    house.handle_message("yarumo/presencia/ocupada", b"false")
    run_for(house, clock, 300)
    for room in ("sala", "cocina", "habitacion_principal", "habitacion_2", "estudio"):
        assert "ON" not in pub.payloads(f"yarumo/casa/movimiento_{room}/estado")


def test_motion_pulses_only_in_rooms_with_devices_on(make_house, clock, pub):
    house = make_house(motion_probability=1.0)
    house.handle_message("yarumo/presencia/ocupada", b"true")
    house.set_device("tv_sala", True)
    run_for(house, clock, 15)
    assert pub.last("yarumo/casa/movimiento_sala/estado") == "ON"
    assert pub.payloads("yarumo/casa/movimiento_cocina/estado") == []
    run_for(house, clock, 30)
    assert "OFF" in pub.payloads("yarumo/casa/movimiento_sala/estado")


def test_leaving_clears_motion(make_house, clock, pub):
    house = make_house(motion_probability=1.0)
    house.handle_message("yarumo/presencia/ocupada", b"true")
    house.set_device("tv_sala", True)
    run_for(house, clock, 15)
    house.handle_message("yarumo/presencia/ocupada", b"false")
    assert pub.last("yarumo/casa/movimiento_sala/estado") == "OFF"


def test_door_pulses_on_occupancy_change_only(make_house, clock, pub):
    house = make_house()
    house.handle_message("yarumo/presencia/ocupada", b"true")  # initial retained value
    assert pub.payloads("yarumo/casa/puerta_principal/estado") == []
    house.handle_message("yarumo/presencia/ocupada", b"false")
    assert pub.last("yarumo/casa/puerta_principal/estado") == "ON"
    run_for(house, clock, 5)
    assert pub.last("yarumo/casa/puerta_principal/estado") == "OFF"


def test_temperature_curve():
    assert medellin_temperature(datetime(2026, 1, 1, 5, 0)) == pytest.approx(18.0)
    assert medellin_temperature(datetime(2026, 1, 1, 14, 0)) == pytest.approx(27.0)
    assert 18.0 < medellin_temperature(datetime(2026, 1, 1, 22, 0)) < 27.0


def test_temperature_published_with_noise(make_house, clock, pub):
    house = make_house()
    house.tick()
    value = float(pub.last("yarumo/casa/temperatura_sala/estado"))
    assert 26.7 <= value <= 27.3


def test_scenarios(make_house):
    house = make_house()
    house.apply_scenario("manana_laboral")
    on = {oid for oid, v in house.on.items() if v}
    assert on == {"luz_cocina", "luz_habitacion_principal", "tv_sala", "pc_estudio"}

    house.apply_scenario("olvido_salida")
    assert {oid for oid, v in house.on.items() if v} == {"tv_sala", "pc_estudio", "luz_estudio"}

    house.apply_scenario("plancha_olvidada")
    assert house.on["plancha_ropa"] and house.on["tv_sala"]

    house.apply_scenario("noche")
    assert {oid for oid, v in house.on.items() if v} == {
        "luz_habitacion_principal",
        "ventilador_habitacion_principal",
    }


def test_reset_keeps_energy(make_house, clock):
    house = make_house()
    house.apply_scenario("manana_laboral")
    run_for(house, clock, 120)
    kwh = dict(house.energy_kwh)
    house.apply_scenario("reset")
    assert not any(house.on.values())
    assert house.energy_kwh == pytest.approx(kwh)


def test_unknown_scenario(make_house):
    with pytest.raises(UnknownScenario):
        make_house().apply_scenario("fiesta")
