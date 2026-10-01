"""House catalog as docs/03-contrato-mqtt.md and docs/04-home-assistant.md define it.

Nominal powers are the documented simulation assumptions; every saving is computed from them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    entity_id: str
    room: str
    power_w: float
    name: str  # user-facing, Spanish

    @property
    def object_id(self) -> str:
        return self.entity_id.split(".", 1)[1]


DEVICES: tuple[Device, ...] = (
    Device("light.luz_sala", "sala", 9, "la luz de la sala"),
    Device("light.luz_cocina", "cocina", 9, "la luz de la cocina"),
    Device("light.luz_habitacion_principal", "habitacion_principal", 9, "la luz de la habitación"),
    Device("light.luz_habitacion_2", "habitacion_2", 9, "la luz de la habitación 2"),
    Device("light.luz_estudio", "estudio", 9, "la luz del estudio"),
    Device("switch.tv_sala", "sala", 90, "la TV"),
    Device("switch.pc_estudio", "estudio", 150, "el PC del estudio"),
    Device("switch.ventilador_habitacion_principal", "habitacion_principal", 55, "el ventilador"),
    Device("switch.plancha_ropa", "habitacion_2", 1000, "la plancha"),
)
DEVICES_BY_ID: dict[str, Device] = {d.entity_id: d for d in DEVICES}
LIGHTS: tuple[Device, ...] = tuple(d for d in DEVICES if d.entity_id.startswith("light."))

ROOMS = ("sala", "cocina", "habitacion_principal", "habitacion_2", "estudio")
MOTION_BY_ROOM: dict[str, str] = {r: f"binary_sensor.movimiento_{r}" for r in ROOMS}

OCCUPANCY = "binary_sensor.casa_ocupada"
RESIDENTS = ("binary_sensor.residente_1_en_casa", "binary_sensor.residente_2_en_casa")
DOOR = "binary_sensor.puerta_principal"
IRON = "switch.plancha_ropa"

ON = "on"
OFF = "off"


def is_power_sensor(entity_id: str) -> bool:
    return entity_id.startswith("sensor.") and entity_id.endswith("_potencia")


def is_tracked(entity_id: str) -> bool:
    """Ingest whitelist (docs/05-savi-ia.md §1)."""
    if entity_id in DEVICES_BY_ID or entity_id in (DOOR, OCCUPANCY):
        return True
    if entity_id.startswith("binary_sensor.movimiento_"):
        return True
    if entity_id.startswith("binary_sensor.residente_") and entity_id.endswith("_en_casa"):
        return True
    return is_power_sensor(entity_id)
