"""Savi MQTT discovery payloads and the bridge with a fake paho client."""

from __future__ import annotations

import json

from savi import mqtt_out


class FakeRC:
    is_failure = False


class FakeClient:
    def __init__(self):
        self.published = []
        self.will = None
        self.connected = True
        self.subscribed = []

    def username_pw_set(self, u, p):
        self.auth = (u, p)

    def will_set(self, topic, payload, qos, retain):
        self.will = (topic, payload, qos, retain)

    def publish(self, topic, payload, qos, retain):
        self.published.append((topic, payload, retain))

    def is_connected(self):
        return self.connected

    def subscribe(self, topics):
        self.subscribed.extend(topics)


def test_discovery_matches_the_contract():
    configs = dict(mqtt_out.discovery_configs())
    assert len(configs) == 5
    energy = configs["homeassistant/sensor/yarumo/savi_energia_evitada/config"]
    assert energy["default_entity_id"] == "sensor.savi_energia_evitada"
    assert energy["unique_id"] == "yarumo_savi_energia_evitada"
    assert (energy["device_class"], energy["state_class"], energy["unit_of_measurement"]) == (
        "energy",
        "total_increasing",
        "kWh",
    )
    assert energy["availability_topic"] == "yarumo/savi/disponible"
    assert energy["device"]["identifiers"] == ["yarumo_savi"]
    money = configs["homeassistant/sensor/yarumo/savi_ahorro_estimado/config"]
    assert (money["device_class"], money["state_class"], money["unit_of_measurement"]) == (
        "monetary",
        "total",
        "COP",
    )
    count = configs["homeassistant/sensor/yarumo/savi_automatizaciones_activas/config"]
    assert "unit_of_measurement" not in count and "device_class" not in count


def test_none_is_published_as_unknown_not_zero():
    payloads = dict(
        mqtt_out.state_payloads(
            {
                "savi_energia_evitada": 0.6,
                "savi_ahorro_estimado": None,
                "savi_sugerencias_pendientes": 2,
            }
        )
    )
    assert payloads["yarumo/savi/savi_energia_evitada/estado"] == "0.6"
    assert payloads["yarumo/savi/savi_ahorro_estimado/estado"] == "None"
    assert payloads["yarumo/savi/savi_sugerencias_pendientes/estado"] == "2"


def test_bridge_sets_lwt_and_announces_on_connect():
    fake = FakeClient()
    out = mqtt_out.MqttOut(
        "h", 1883, "u", "p", lambda: {"savi_automatizaciones_activas": 1}, lambda: fake
    )
    assert fake.will == ("yarumo/savi/disponible", "offline", 1, True)
    out._on_connect(fake, None, None, FakeRC())
    topics = [t for t, _, _ in fake.published]
    assert topics.index("yarumo/savi/disponible") > max(
        i for i, t in enumerate(topics) if t.endswith("/config")
    )
    assert all(retain for _, _, retain in fake.published)
    assert ("yarumo/savi/savi_automatizaciones_activas/estado", "1", True) in fake.published
    cfg = next(p for t, p, _ in fake.published if t.endswith("savi_ahorro_estimado/config"))
    assert json.loads(cfg)["name"] == "Ahorro (estimado)"

    fake.published.clear()
    fake.connected = False
    out.publish_states()
    assert fake.published == []
