"""Static catalog of rooms, devices and sensors, exactly as docs/03-contrato-mqtt.md defines."""

from __future__ import annotations

from dataclasses import dataclass

BASE = "yarumo/casa"
AVAILABILITY_TOPIC = f"{BASE}/disponible"
OCCUPANCY_TOPIC = "yarumo/presencia/ocupada"
HA_STATUS_TOPIC = "homeassistant/status"
DISCOVERY_PREFIX = "homeassistant"

# room key -> display name (also used as suggested_area)
ROOMS: dict[str, str] = {
    "sala": "Sala",
    "cocina": "Cocina",
    "habitacion_principal": "Habitación principal",
    "habitacion_2": "Habitación 2",
    "estudio": "Estudio",
}


@dataclass(frozen=True)
class Device:
    object_id: str
    component: str  # "light" | "switch"
    room: str
    power_on_w: float
    standby_w: float
    name: str
    icon: str | None = None

    def topic(self, leaf: str) -> str:
        return f"{BASE}/{self.object_id}/{leaf}"


@dataclass(frozen=True)
class Sensor:
    object_id: str
    component: str  # "binary_sensor" | "sensor"
    device_class: str
    room: str
    name: str

    @property
    def state_topic(self) -> str:
        return f"{BASE}/{self.object_id}/estado"


DEVICES: tuple[Device, ...] = (
    Device("luz_sala", "light", "sala", 9, 0, "Luz"),
    Device("luz_cocina", "light", "cocina", 9, 0, "Luz"),
    Device("luz_habitacion_principal", "light", "habitacion_principal", 9, 0, "Luz"),
    Device("luz_habitacion_2", "light", "habitacion_2", 9, 0, "Luz"),
    Device("luz_estudio", "light", "estudio", 9, 0, "Luz"),
    Device("tv_sala", "switch", "sala", 90, 1, "TV", "mdi:television"),
    Device("pc_estudio", "switch", "estudio", 150, 2, "PC", "mdi:desktop-tower-monitor"),
    Device(
        "ventilador_habitacion_principal",
        "switch",
        "habitacion_principal",
        55,
        0,
        "Ventilador",
        "mdi:fan",
    ),
    Device("plancha_ropa", "switch", "habitacion_2", 1000, 0, "Plancha", "mdi:iron"),
)

# The contract does not assign a room to puerta_principal; it is grouped with "sala".
SENSORS: tuple[Sensor, ...] = (
    Sensor("movimiento_sala", "binary_sensor", "motion", "sala", "Movimiento"),
    Sensor("movimiento_cocina", "binary_sensor", "motion", "cocina", "Movimiento"),
    Sensor(
        "movimiento_habitacion_principal",
        "binary_sensor",
        "motion",
        "habitacion_principal",
        "Movimiento",
    ),
    Sensor("movimiento_habitacion_2", "binary_sensor", "motion", "habitacion_2", "Movimiento"),
    Sensor("movimiento_estudio", "binary_sensor", "motion", "estudio", "Movimiento"),
    Sensor("puerta_principal", "binary_sensor", "door", "sala", "Puerta principal"),
    Sensor("temperatura_sala", "sensor", "temperature", "sala", "Temperatura"),
)

DEVICES_BY_ID: dict[str, Device] = {d.object_id: d for d in DEVICES}
MOTION_BY_ROOM: dict[str, Sensor] = {s.room: s for s in SENSORS if s.device_class == "motion"}
DOOR = next(s for s in SENSORS if s.device_class == "door")
TEMPERATURE = next(s for s in SENSORS if s.device_class == "temperature")
