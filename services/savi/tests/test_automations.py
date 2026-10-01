"""Automation templates (docs/05-savi-ia.md §3) and notification payloads/parsing."""

from __future__ import annotations

import pytest

from savi import automations, notifications

from .conftest import END, TZ


def suggestion(detector, entities, sid=2, title="Apagar lo que queda encendido al salir"):
    return {
        "id": sid,
        "detector": detector,
        "title": title,
        "entities": entities,
        "evidence": {"resumen": "la TV: 12 de 15 salidas"},
        "explanation": "Cuando la casa queda sola, se queda prendida la TV.",
    }


def test_d1_payload_matches_the_spec():
    cfg = automations.build(
        suggestion("olvido_al_salir", ["switch.pc_estudio", "switch.tv_sala"]),
        END.timestamp(),
        TZ,
    )
    assert cfg["alias"] == "Savi · Apagar lo que queda encendido al salir"
    assert "12 de 15 salidas" in cfg["description"] and "2026-09-30" in cfg["description"]
    assert cfg["mode"] == "single"
    assert cfg["triggers"] == [
        {"trigger": "state", "entity_id": "binary_sensor.casa_ocupada", "to": "off"}
    ]
    turn_off, notify = cfg["actions"]
    assert turn_off == {
        "action": "homeassistant.turn_off",
        "target": {"entity_id": ["switch.pc_estudio", "switch.tv_sala"]},
    }
    assert notify["action"] == "notify.residentes" and notify["continue_on_error"] is True
    assert notify["data"]["message"] == ("Nadie quedó en casa. Apagué el PC del estudio y la TV.")


def test_d2_d3_r1_payloads():
    d2 = automations.build(suggestion("luz_sin_movimiento", ["light.luz_cocina"]), 0, TZ)
    assert d2["triggers"][0]["entity_id"] == "binary_sensor.movimiento_cocina"
    assert d2["triggers"][0]["for"] == {"minutes": 20}
    assert d2["actions"][0]["target"]["entity_id"] == ["light.luz_cocina"]

    d3 = automations.build(suggestion("consumo_nocturno", ["switch.pc_estudio"]), 0, TZ)
    assert {"condition": "time", "after": "01:00:00", "before": "06:00:00"} in d3["conditions"]
    assert d3["triggers"][1]["entity_id"] == "binary_sensor.movimiento_estudio"

    r1 = automations.build(suggestion("plancha_olvidada", ["switch.plancha_ropa"]), 0, TZ)
    assert [t["entity_id"] for t in r1["triggers"]] == [
        "binary_sensor.casa_ocupada",
        "switch.plancha_ropa",
    ]
    assert r1["actions"][1]["data"]["data"]["priority"] == "high"

    with pytest.raises(ValueError):
        automations.build(suggestion("otro", []), 0, TZ)
    assert automations.automation_id(7) == "savi_7"


def test_actionable_notification_payload():
    msg = notifications.suggestion_message(suggestion("olvido_al_salir", ["switch.tv_sala"], sid=5))
    assert msg["title"].startswith("Savi · ")
    assert msg["data"]["actions"] == [
        {"action": "SAVI_APROBAR::5", "title": "Activar"},
        {"action": "SAVI_RECHAZAR::5", "title": "Ahora no"},
    ]
    assert msg["data"]["tag"] == "savi_sugerencia_5"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"action": "SAVI_APROBAR::12"}, ("aprobar", 12)),
        ({"action": "SAVI_RECHAZAR::3"}, ("rechazar", 3)),
        ({"actionName": "SAVI_APROBAR::4"}, ("aprobar", 4)),
        ({"action": "SAVI_APROBAR::x"}, None),
        ({"action": "OTRA::1"}, None),
        ({"action": "SAVI_APROBAR"}, None),
        ({}, None),
    ],
)
def test_parse_notification_action(data, expected):
    assert notifications.parse_action(data) == expected
