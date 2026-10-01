"""Savi's sensors in HA via MQTT discovery (docs/03-contrato-mqtt.md, "Sensores de Savi").

Mirrors sim-casa's bridge: paho-mqtt 2.x, LWT on the availability topic, discovery re-sent on
connect and when HA announces `homeassistant/status = online`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt

log = logging.getLogger("savi.mqtt")

QOS = 1
BASE = "yarumo/savi"
AVAILABILITY_TOPIC = f"{BASE}/disponible"
HA_STATUS_TOPIC = "homeassistant/status"
DISCOVERY_PREFIX = "homeassistant"
NONE_PAYLOAD = "None"  # HA's MQTT sensor reads this as "unknown"; never a made-up zero

DEVICE = {
    "identifiers": ["yarumo_savi"],
    "name": "Savi",
    "manufacturer": "Yarumo",
    "model": "savi",
}


@dataclass(frozen=True)
class SensorSpec:
    object_id: str
    name: str
    unit: str | None
    device_class: str | None
    state_class: str | None
    icon: str


SENSORS: tuple[SensorSpec, ...] = (
    SensorSpec(
        "savi_energia_evitada",
        "Energía evitada (estimado)",
        "kWh",
        "energy",
        "total_increasing",
        "mdi:leaf",
    ),
    SensorSpec("savi_ahorro_estimado", "Ahorro (estimado)", "COP", "monetary", "total", "mdi:cash"),
    SensorSpec(
        "savi_ahorro_mensual_proyectado",
        "Ahorro mensual proyectado (estimado)",
        "COP",
        "monetary",
        "total",
        "mdi:calendar-month",
    ),
    SensorSpec(
        "savi_automatizaciones_activas",
        "Automatizaciones activas",
        None,
        None,
        "measurement",
        "mdi:robot",
    ),
    SensorSpec(
        "savi_sugerencias_pendientes",
        "Sugerencias pendientes",
        None,
        None,
        "measurement",
        "mdi:lightbulb-question",
    ),
)


def state_topic(object_id: str) -> str:
    return f"{BASE}/{object_id}/estado"


def discovery_topic(object_id: str) -> str:
    return f"{DISCOVERY_PREFIX}/sensor/yarumo/{object_id}/config"


def discovery_configs() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for s in SENSORS:
        cfg: dict[str, Any] = {
            "name": s.name,
            "unique_id": f"yarumo_{s.object_id}",
            "object_id": s.object_id,
            "default_entity_id": f"sensor.{s.object_id}",
            "state_topic": state_topic(s.object_id),
            "availability_topic": AVAILABILITY_TOPIC,
            "qos": QOS,
            "icon": s.icon,
            "device": DEVICE,
        }
        if s.unit:
            cfg["unit_of_measurement"] = s.unit
        if s.device_class:
            cfg["device_class"] = s.device_class
        if s.state_class:
            cfg["state_class"] = s.state_class
        out.append((discovery_topic(s.object_id), cfg))
    return out


def state_payloads(values: dict[str, float | int | None]) -> list[tuple[str, str]]:
    out = []
    for s in SENSORS:
        v = values.get(s.object_id)
        out.append((state_topic(s.object_id), NONE_PAYLOAD if v is None else json.dumps(v)))
    return out


def default_client_factory() -> Any:
    return mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id="yarumo-savi"
    )


class MqttOut:
    def __init__(
        self,
        host: str,
        port: int,
        user: str | None,
        password: str | None,
        values: Callable[[], dict[str, float | int | None]],
        client_factory: Callable[[], Any] = default_client_factory,
    ) -> None:
        self.host = host
        self.port = port
        self.values = values
        self.client = client_factory()
        if user:
            self.client.username_pw_set(user, password)
        self.client.will_set(AVAILABILITY_TOPIC, "offline", qos=QOS, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def is_connected(self) -> bool:
        return bool(self.client.is_connected())

    def _publish(self, topic: str, payload: str) -> None:
        self.client.publish(topic, payload, qos=QOS, retain=True)

    def publish_discovery(self) -> None:
        for topic, cfg in discovery_configs():
            self._publish(topic, json.dumps(cfg, ensure_ascii=False))

    def publish_states(self) -> None:
        if not self.is_connected():
            return
        try:
            payloads = state_payloads(self.values())
        except Exception:
            log.exception("could not compute Savi sensor values")
            return
        for topic, payload in payloads:
            self._publish(topic, payload)

    def start(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        try:
            info = self.client.publish(AVAILABILITY_TOPIC, "offline", qos=QOS, retain=True)
            info.wait_for_publish(timeout=2)
        except Exception:  # noqa: BLE001 - best effort on shutdown
            log.warning("could not publish offline on shutdown")
        self.client.disconnect()
        self.client.loop_stop()

    def _announce(self) -> None:
        self.publish_discovery()
        self._publish(AVAILABILITY_TOPIC, "online")
        for topic, payload in state_payloads(self.values()):
            self._publish(topic, payload)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("MQTT connected to %s:%s", self.host, self.port)
        client.subscribe([(HA_STATUS_TOPIC, QOS)])
        self._announce()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        if message.topic == HA_STATUS_TOPIC and message.payload.decode(errors="replace") == (
            "online"
        ):
            self._announce()
