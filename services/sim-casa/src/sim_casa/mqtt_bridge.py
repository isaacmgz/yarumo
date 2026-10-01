"""paho-mqtt 2.x adapter: LWT, discovery, subscriptions and the Publisher implementation."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from .catalog import AVAILABILITY_TOPIC, BASE, HA_STATUS_TOPIC, OCCUPANCY_TOPIC
from .discovery import all_configs

log = logging.getLogger(__name__)

QOS = 1
COMMAND_TOPIC = f"{BASE}/+/set"


def default_client_factory() -> Any:
    return mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="yarumo-sim-casa",
    )


class MqttBridge:
    """Owns the MQTT connection. `on_message_cb` receives (topic, payload bytes)."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str | None,
        password: str | None,
        client_factory: Callable[[], Any] = default_client_factory,
    ):
        self.host = host
        self.port = port
        self.client = client_factory()
        if user:
            self.client.username_pw_set(user, password)
        # LWT: the broker marks every entity unavailable if this process dies.
        self.client.will_set(AVAILABILITY_TOPIC, "offline", qos=QOS, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.on_message_cb: Callable[[str, bytes], None] | None = None
        self.on_connected_cb: Callable[[], None] | None = None

    # Publisher protocol
    def publish(self, topic: str, payload: str, retain: bool = True) -> None:
        self.client.publish(topic, payload, qos=QOS, retain=retain)

    def is_connected(self) -> bool:
        return bool(self.client.is_connected())

    def publish_discovery(self) -> None:
        for topic, config in all_configs():
            self.publish(topic, json.dumps(config, ensure_ascii=False), retain=True)

    def start(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        try:
            info = self.client.publish(AVAILABILITY_TOPIC, "offline", qos=QOS, retain=True)
            info.wait_for_publish(timeout=2)
        except Exception:  # noqa: BLE001 - best effort on shutdown
            log.warning("Could not publish offline on shutdown")
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("MQTT connected to %s:%s", self.host, self.port)
        self.publish_discovery()
        client.subscribe([(COMMAND_TOPIC, QOS), (OCCUPANCY_TOPIC, QOS), (HA_STATUS_TOPIC, QOS)])
        if self.on_connected_cb:
            self.on_connected_cb()
        self.publish(AVAILABILITY_TOPIC, "online", retain=True)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        log.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        topic, payload = message.topic, message.payload
        if topic == HA_STATUS_TOPIC:
            # HA restarted: re-announce discovery and current states.
            if payload.decode(errors="replace").strip() == "online":
                self.publish_discovery()
                if self.on_connected_cb:
                    self.on_connected_cb()
            return
        if self.on_message_cb is None:
            return
        try:
            self.on_message_cb(topic, payload)
        except Exception:
            log.exception("Error handling message on %s", topic)
