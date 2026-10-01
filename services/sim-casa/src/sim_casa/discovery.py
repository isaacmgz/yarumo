"""Home Assistant MQTT discovery payloads (docs/03-contrato-mqtt.md)."""

from __future__ import annotations

from typing import Any

from .catalog import (
    AVAILABILITY_TOPIC,
    DEVICES,
    DISCOVERY_PREFIX,
    ROOMS,
    SENSORS,
    Device,
    Sensor,
)


def room_device(room: str) -> dict[str, Any]:
    return {
        "identifiers": [f"yarumo_{room}"],
        "name": ROOMS[room],
        "manufacturer": "Yarumo (simulado)",
        "model": "sim-casa",
        "suggested_area": ROOMS[room],
    }


def _base(component: str, object_id: str, name: str, state_topic: str, room: str) -> dict:
    return {
        "name": name,
        "unique_id": f"yarumo_{object_id}",
        # `object_id` is what the contract names; HA >= 2026.4 ignores it and uses
        # `default_entity_id` instead, so both are sent to pin the final entity_id.
        "object_id": object_id,
        "default_entity_id": f"{component}.{object_id}",
        "state_topic": state_topic,
        "availability_topic": AVAILABILITY_TOPIC,
        "qos": 1,
        "device": room_device(room),
    }


def topic(component: str, object_id: str) -> str:
    return f"{DISCOVERY_PREFIX}/{component}/yarumo/{object_id}/config"


def device_configs(device: Device) -> list[tuple[str, dict[str, Any]]]:
    oid = device.object_id
    main = _base(device.component, oid, device.name, device.topic("estado"), device.room)
    main["command_topic"] = device.topic("set")
    main["payload_on"] = "ON"
    main["payload_off"] = "OFF"
    if device.icon:
        main["icon"] = device.icon

    power = _base(
        "sensor",
        f"{oid}_potencia",
        f"{device.name} potencia",
        device.topic("potencia"),
        device.room,
    )
    power.update(device_class="power", unit_of_measurement="W", state_class="measurement")

    energy = _base(
        "sensor", f"{oid}_energia", f"{device.name} energía", device.topic("energia"), device.room
    )
    energy.update(device_class="energy", unit_of_measurement="kWh", state_class="total_increasing")

    return [
        (topic(device.component, oid), main),
        (topic("sensor", f"{oid}_potencia"), power),
        (topic("sensor", f"{oid}_energia"), energy),
    ]


def sensor_config(sensor: Sensor) -> tuple[str, dict[str, Any]]:
    cfg = _base(sensor.component, sensor.object_id, sensor.name, sensor.state_topic, sensor.room)
    cfg["device_class"] = sensor.device_class
    if sensor.component == "binary_sensor":
        cfg["payload_on"] = "ON"
        cfg["payload_off"] = "OFF"
    else:
        cfg["unit_of_measurement"] = "°C"
        cfg["state_class"] = "measurement"
    return topic(sensor.component, sensor.object_id), cfg


def all_configs() -> list[tuple[str, dict[str, Any]]]:
    configs: list[tuple[str, dict[str, Any]]] = []
    for device in DEVICES:
        configs.extend(device_configs(device))
    configs.extend(sensor_config(s) for s in SENSORS)
    return configs
