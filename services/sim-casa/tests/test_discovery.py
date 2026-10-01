"""Contract: discovery topics and payloads match docs/03-contrato-mqtt.md."""

from __future__ import annotations

from collections import Counter

from sim_casa.catalog import AVAILABILITY_TOPIC
from sim_casa.discovery import all_configs

EXPECTED_DEVICES = {
    "luz_sala": ("light", "sala"),
    "luz_cocina": ("light", "cocina"),
    "luz_habitacion_principal": ("light", "habitacion_principal"),
    "luz_habitacion_2": ("light", "habitacion_2"),
    "luz_estudio": ("light", "estudio"),
    "tv_sala": ("switch", "sala"),
    "pc_estudio": ("switch", "estudio"),
    "ventilador_habitacion_principal": ("switch", "habitacion_principal"),
    "plancha_ropa": ("switch", "habitacion_2"),
}
EXPECTED_SENSORS = {
    "movimiento_sala": ("binary_sensor", "motion"),
    "movimiento_cocina": ("binary_sensor", "motion"),
    "movimiento_habitacion_principal": ("binary_sensor", "motion"),
    "movimiento_habitacion_2": ("binary_sensor", "motion"),
    "movimiento_estudio": ("binary_sensor", "motion"),
    "puerta_principal": ("binary_sensor", "door"),
    "temperatura_sala": ("sensor", "temperature"),
}


def _by_object_id() -> dict[str, tuple[str, dict]]:
    return {cfg["object_id"]: (topic, cfg) for topic, cfg in all_configs()}


def test_34_entities_with_unique_ids():
    configs = all_configs()
    assert len(configs) == 9 * 3 + 7 == 34
    unique_ids = Counter(cfg["unique_id"] for _, cfg in configs)
    assert all(n == 1 for n in unique_ids.values())


def test_controllable_devices_expose_three_entities():
    by_oid = _by_object_id()
    for oid, (component, room) in EXPECTED_DEVICES.items():
        topic, main = by_oid[oid]
        assert topic == f"homeassistant/{component}/yarumo/{oid}/config"
        assert main["unique_id"] == f"yarumo_{oid}"
        assert main["default_entity_id"] == f"{component}.{oid}"
        assert main["state_topic"] == f"yarumo/casa/{oid}/estado"
        assert main["command_topic"] == f"yarumo/casa/{oid}/set"
        assert main["device"]["identifiers"] == [f"yarumo_{room}"]

        topic, power = by_oid[f"{oid}_potencia"]
        assert topic == f"homeassistant/sensor/yarumo/{oid}_potencia/config"
        assert power["default_entity_id"] == f"sensor.{oid}_potencia"
        assert power["state_topic"] == f"yarumo/casa/{oid}/potencia"
        assert (power["device_class"], power["unit_of_measurement"], power["state_class"]) == (
            "power",
            "W",
            "measurement",
        )

        topic, energy = by_oid[f"{oid}_energia"]
        assert topic == f"homeassistant/sensor/yarumo/{oid}_energia/config"
        assert energy["default_entity_id"] == f"sensor.{oid}_energia"
        assert energy["state_topic"] == f"yarumo/casa/{oid}/energia"
        assert (energy["device_class"], energy["unit_of_measurement"], energy["state_class"]) == (
            "energy",
            "kWh",
            "total_increasing",
        )


def test_sensors():
    by_oid = _by_object_id()
    for oid, (component, device_class) in EXPECTED_SENSORS.items():
        topic, cfg = by_oid[oid]
        assert topic == f"homeassistant/{component}/yarumo/{oid}/config"
        assert cfg["default_entity_id"] == f"{component}.{oid}"
        assert cfg["state_topic"] == f"yarumo/casa/{oid}/estado"
        assert cfg["device_class"] == device_class
        assert "command_topic" not in cfg


def test_common_fields_match_contract_example():
    by_oid = _by_object_id()
    _, tv = by_oid["tv_sala"]
    assert tv["name"] == "TV"
    assert tv["icon"] == "mdi:television"
    assert tv["device"] == {
        "identifiers": ["yarumo_sala"],
        "name": "Sala",
        "manufacturer": "Yarumo (simulado)",
        "model": "sim-casa",
        "suggested_area": "Sala",
    }
    for _, cfg in all_configs():
        assert cfg["availability_topic"] == AVAILABILITY_TOPIC == "yarumo/casa/disponible"
        assert cfg["qos"] == 1
        assert cfg["device"]["manufacturer"] == "Yarumo (simulado)"
