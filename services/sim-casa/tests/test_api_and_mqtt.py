"""Scenario API and MQTT adapter (no live broker)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from sim_casa.api import create_app
from sim_casa.mqtt_bridge import MqttBridge


def test_api(make_house, pub):
    house = make_house()
    client = TestClient(create_app(house, lambda: True))

    assert client.get("/health").json() == {"ok": True, "mqtt": "connected"}

    devices = client.get("/dispositivos").json()
    assert len(devices) == 9
    assert {"id", "estado", "potencia_w", "energia_kwh"} <= devices[0].keys()

    r = client.post("/dispositivos/tv_sala", json={"estado": "ON"})
    assert r.status_code == 200
    assert r.json()["estado"] == "ON" and r.json()["potencia_w"] == 90
    assert pub.last("yarumo/casa/tv_sala/estado") == "ON"

    assert client.post("/dispositivos/nevera", json={"estado": "ON"}).status_code == 404
    assert client.post("/dispositivos/tv_sala", json={"estado": "TAL VEZ"}).status_code == 422

    r = client.post("/escenarios/noche")
    assert r.status_code == 200 and r.json()["escenario"] == "noche"
    assert client.post("/escenarios/fiesta").status_code == 404


def test_health_reports_disconnected(make_house):
    client = TestClient(create_app(make_house(), lambda: False))
    assert client.get("/health").json()["mqtt"] == "disconnected"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.published: list[tuple] = []
        self.subscriptions: list = []

    def username_pw_set(self, user, password):
        self.calls.append(("auth", user, password))

    def will_set(self, topic, payload, qos, retain):
        self.calls.append(("will", topic, payload, qos, retain))

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, qos, retain))

    def subscribe(self, topics):
        self.subscriptions.extend(topics)


def _bridge() -> tuple[MqttBridge, FakeClient]:
    fake = FakeClient()
    bridge = MqttBridge("127.0.0.1", 1883, "yarumo", "secreto", client_factory=lambda: fake)
    return bridge, fake


def test_lwt_is_offline_retained():
    _, fake = _bridge()
    assert ("will", "yarumo/casa/disponible", "offline", 1, True) in fake.calls
    assert ("auth", "yarumo", "secreto") in fake.calls


def test_on_connect_publishes_discovery_then_online_and_subscribes():
    bridge, fake = _bridge()
    states = []
    bridge.on_connected_cb = lambda: states.append("published")
    bridge._on_connect(fake, None, None, SimpleNamespace(is_failure=False))

    discovery = [p for p in fake.published if p[0].startswith("homeassistant/")]
    assert len(discovery) == 34
    assert all(qos == 1 and retain for _, _, qos, retain in discovery)
    json.loads(discovery[0][1])
    assert fake.published[-1] == ("yarumo/casa/disponible", "online", 1, True)
    assert states == ["published"]
    subscribed = {t for t, _ in fake.subscriptions}
    assert {"yarumo/casa/+/set", "yarumo/presencia/ocupada"} <= subscribed


def test_messages_are_routed_to_house(make_house, pub):
    bridge, fake = _bridge()
    house = make_house()
    bridge.on_message_cb = house.handle_message
    bridge._on_message(fake, None, SimpleNamespace(topic="yarumo/casa/luz_sala/set", payload=b"ON"))
    assert pub.last("yarumo/casa/luz_sala/estado") == "ON"
    assert pub.last("yarumo/casa/luz_sala/potencia") == "9.0"


def test_ha_birth_republishes_discovery():
    bridge, fake = _bridge()
    bridge._on_message(fake, None, SimpleNamespace(topic="homeassistant/status", payload=b"online"))
    assert len([p for p in fake.published if p[0].startswith("homeassistant/")]) == 34
