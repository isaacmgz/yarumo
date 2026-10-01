"""H4 flows with a fake Home Assistant: approve/deactivate, phone actions, savings lifecycle."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from savi.api import Savi, create_app
from savi.ha_client import HaError
from savi.suggestions import Tariff

from .conftest import END, TZ
from .test_suggestions_api import NOW, Clock, _probe


class FakeHa:
    def __init__(self, fail_create=False, missing=False):
        self.calls: list[tuple] = []
        self.created: dict[str, dict] = {}
        self.fail_create = fail_create
        self.missing = missing

    async def call_service(self, domain, service, data=None):
        self.calls.append((domain, service, data))

    async def create_automation(self, automation_id, config):
        if self.fail_create:
            raise HaError("boom")
        self.created[automation_id] = config
        return "config_api"

    async def wait_for_automation(self, automation_id):
        if self.missing:
            return None
        return f"automation.alias_of_{automation_id}"

    def services(self, domain, service):
        return [d for dom, srv, d in self.calls if (dom, srv) == (domain, service)]


def d1(store, now=NOW, status="nueva"):
    sid = store.insert_suggestion(
        {
            "detector": "olvido_al_salir",
            "dedup_key": "olvido_al_salir:switch.pc_estudio,switch.tv_sala",
            "title": "Apagar lo que queda encendido al salir",
            "entities": ["switch.pc_estudio", "switch.tv_sala"],
            "evidence": {"resumen": "la TV: 12 de 15 salidas", "datos_simulados": True},
            "est_kwh_month": 55.46,
            "est_cop_month": None,
            "confidence": "alta",
            "explanation": "Cuando la casa queda sola, se queda prendida la TV.",
        },
        now,
    )
    if status != "nueva":
        store.set_status(sid, status, now)
    return sid


NO_TARIFF = Tariff(0, False)


def make(store, ha=None, tariff=NO_TARIFF, clock=None):
    changes = []
    savi = Savi(
        store,
        TZ,
        tariff,
        clock or Clock(NOW),
        True,
        ha=ha,
        cache={},
        on_change=lambda: changes.append(1),
    )
    return savi, changes


def run(coro):
    return asyncio.run(coro)


# ---- approve / deactivate -------------------------------------------------


def test_approve_via_api_creates_automation_and_activates(store):
    ha = FakeHa()
    savi, changes = make(store, ha)
    sid = d1(store)
    client = TestClient(create_app(savi, _probe))

    body = client.post(f"/api/sugerencias/{sid}/aprobar").json()
    assert body["estado"] == "activa"
    assert body["automation_id"] == f"automation.alias_of_savi_{sid}"
    assert body["decidida_por"] == "panel"
    cfg = ha.created[f"savi_{sid}"]
    assert cfg["alias"] == "Savi · Apagar lo que queda encendido al salir"
    assert ha.services("automation", "turn_on") == [{"entity_id": body["automation_id"]}]
    assert ha.services("notify", "residentes")[-1]["message"] == (
        "Listo, ya quedó. Te cuento cuando actúe."
    )
    assert changes

    # Approving again is idempotent: no second automation.
    ha.created.clear()
    assert client.post(f"/api/sugerencias/{sid}/aprobar").json()["estado"] == "activa"
    assert ha.created == {}


def test_approve_failure_keeps_aprobada_and_returns_502(store):
    savi, _ = make(store, FakeHa(fail_create=True))
    sid = d1(store)
    client = TestClient(create_app(savi, _probe))
    r = client.post(f"/api/sugerencias/{sid}/aprobar")
    assert r.status_code == 502 and "No pude crear" in r.json()["detail"]
    assert store.get_suggestion(sid)["status"] == "aprobada"

    savi2, _ = make(store, FakeHa(missing=True))
    r = TestClient(create_app(savi2, _probe)).post(f"/api/sugerencias/{sid}/aprobar")
    assert r.status_code == 502


def test_approve_without_ha_is_a_clear_error(store):
    savi, _ = make(store, None)
    sid = d1(store)
    r = TestClient(create_app(savi, _probe)).post(f"/api/sugerencias/{sid}/aprobar")
    assert r.status_code == 502 and "HA_TOKEN" in r.json()["detail"]
    assert store.get_suggestion(sid)["status"] == "nueva"


def test_deactivate_turns_the_automation_off(store):
    ha = FakeHa()
    savi, _ = make(store, ha)
    sid = d1(store)
    run(savi.approve(sid))
    client = TestClient(create_app(savi, _probe))
    body = client.post(f"/api/sugerencias/{sid}/desactivar").json()
    assert body["estado"] == "desactivada"
    assert ha.services("automation", "turn_off") == [{"entity_id": body["automation_id"]}]
    assert client.post(f"/api/sugerencias/{sid}/desactivar", params={"via": "x"}).status_code == 422


# ---- notifications and phone actions --------------------------------------


def test_new_suggestions_are_notified_once_with_actions(store):
    ha = FakeHa()
    savi, _ = make(store, ha)
    sid = d1(store)
    assert run(savi.notify_new()) == 1
    assert run(savi.notify_new()) == 0
    push = ha.services("notify", "residentes")[0]
    assert push["data"]["actions"][0]["action"] == f"SAVI_APROBAR::{sid}"
    assert ha.services("persistent_notification", "create")[0]["notification_id"] == (
        f"savi_sugerencia_{sid}"
    )
    assert store.get_suggestion(sid)["status"] == "notificada"


def test_phone_approve_action_creates_the_automation(store):
    ha = FakeHa()
    savi, _ = make(store, ha)
    sid = d1(store, status="notificada")
    run(savi.handle_ha_event("mobile_app_notification_action", {"action": f"SAVI_APROBAR::{sid}"}))
    s = store.get_suggestion(sid)
    assert (s["status"], s["decided_via"]) == ("activa", "celular")
    assert f"savi_{sid}" in ha.created


def test_phone_reject_action_and_unknown_ids(store):
    ha = FakeHa()
    savi, _ = make(store, ha)
    sid = d1(store, status="notificada")
    run(savi.handle_ha_event("mobile_app_notification_action", {"action": f"SAVI_RECHAZAR::{sid}"}))
    assert store.get_suggestion(sid)["status"] == "rechazada"
    assert "14 días" in ha.services("notify", "residentes")[-1]["message"]
    # Unknown id and foreign actions are ignored without raising.
    run(savi.handle_ha_event("mobile_app_notification_action", {"action": "SAVI_APROBAR::999"}))
    run(savi.handle_ha_event("mobile_app_notification_action", {"action": "OTRA_APP"}))
    assert ha.created == {}


# ---- savings lifecycle ----------------------------------------------------


def _on(savi, entity_id, power=None):
    savi.cache[entity_id] = {"state": "on"}
    if power is not None:
        oid = entity_id.split(".", 1)[1]
        savi.cache[f"sensor.{oid}_potencia"] = {"state": str(power)}


def test_record_opens_on_trigger_grows_live_and_closes_on_return(store):
    clock = Clock(NOW)
    ha = FakeHa()
    savi, _ = make(store, ha, Tariff(800, True), clock)
    sid = d1(store)
    run(savi.approve(sid))
    entity = store.get_suggestion(sid)["automation_id"]
    _on(savi, "switch.tv_sala", 90.0)
    _on(savi, "switch.pc_estudio")  # no power reading -> nominal 150 W from the contract

    run(savi.handle_ha_event("automation_triggered", {"entity_id": entity}))
    run(savi.handle_ha_event("automation_triggered", {"entity_id": entity}))  # no duplicate
    open_ = store.savings("en_curso")
    assert len(open_) == 1 and open_[0]["power_w"] == 240.0

    clock.now += 1800
    live = savi.ahorro()["en_curso"][0]
    assert live["horas"] == 0.5 and live["kwh"] == 0.12 and live["cop"] == 96
    clock.now += 1800
    assert savi.ahorro()["en_curso"][0]["kwh"] == 0.24  # grows

    # Someone else's motion does not close a D1 record; the house becoming occupied does.
    run(savi.handle_ha_event("state_changed", _changed("binary_sensor.movimiento_sala", "on")))
    assert store.savings("en_curso")
    clock.now += 3600 * 1.5  # 2.5 h in total
    run(savi.handle_ha_event("state_changed", _changed("binary_sensor.casa_ocupada", "on")))
    (closed,) = store.savings("cerrado")
    # By hand: (90 + 150) W × 2.5 h / 1000 = 0.6 kWh; 0.6 kWh × 800 COP/kWh = 480 COP.
    assert (closed["hours"], closed["kwh"], closed["cop"]) == (2.5, 0.6, 480)
    a = savi.ahorro()
    assert a["acumulado"] == {"kwh": 0.6, "cop": 480}
    assert a["en_curso"] == []
    assert "datos simulados" in a["etiquetas"] and "estimado" in a["etiquetas"]


def trigger(savi, sid):
    entity = f"automation.alias_of_savi_{sid}"
    run(savi.handle_ha_event("automation_triggered", {"entity_id": entity}))


def _changed(entity_id, state):
    return {"entity_id": entity_id, "new_state": {"state": state}}


def test_nothing_on_means_no_record(store):
    savi, _ = make(store, FakeHa())
    sid = d1(store)
    run(savi.approve(sid))
    entity = store.get_suggestion(sid)["automation_id"]
    run(savi.handle_ha_event("automation_triggered", {"entity_id": entity}))
    run(savi.handle_ha_event("automation_triggered", {"entity_id": "automation.not_savi"}))
    assert store.savings() == []


def test_eight_hour_cap_closes_on_tick(store):
    clock = Clock(NOW)
    savi, _ = make(store, FakeHa(), Tariff(0, False), clock)
    sid = d1(store)
    run(savi.approve(sid))
    _on(savi, "switch.tv_sala", 90)
    trigger(savi, sid)
    clock.now += 7.9 * 3600
    assert savi.tick() == []
    clock.now += 3 * 3600
    assert savi.ahorro()["en_curso"][0]["horas"] == 8.0  # live view is capped too
    assert len(savi.tick()) == 1
    (closed,) = store.savings("cerrado")
    assert closed["hours"] == 8.0 and closed["kwh"] == 0.72
    assert closed["ended_at"] == pytest.approx(NOW + 8 * 3600)
    assert closed["cop"] is None  # no tariff: kWh only, never an invented peso figure
    assert "tarifa sin verificar" in savi.ahorro()["etiquetas"]


def test_d3_closes_at_six_and_d2_on_motion(store):
    # 02:00 local
    start = END.timestamp() + 2 * 3600
    clock = Clock(start)
    savi, _ = make(store, FakeHa(), Tariff(0, False), clock)
    d3 = store.insert_suggestion(
        {
            "detector": "consumo_nocturno",
            "dedup_key": "consumo_nocturno:switch.pc_estudio",
            "title": "Apagar el PC del estudio de madrugada",
            "entities": ["switch.pc_estudio"],
            "evidence": {},
            "est_kwh_month": 7.7,
            "est_cop_month": None,
            "confidence": "media",
            "explanation": "x",
        },
        start,
    )
    d2 = store.insert_suggestion(
        {
            "detector": "luz_sin_movimiento",
            "dedup_key": "luz_sin_movimiento:light.luz_cocina",
            "title": "Apagar la luz de la cocina cuando nadie está ahí",
            "entities": ["light.luz_cocina"],
            "evidence": {},
            "est_kwh_month": 0.05,
            "est_cop_month": None,
            "confidence": "media",
            "explanation": "x",
        },
        start,
    )
    for sid in (d3, d2):
        run(savi.approve(sid))
    _on(savi, "switch.pc_estudio", 150)
    _on(savi, "light.luz_cocina", 9)
    for sid in (d3, d2):
        entity = store.get_suggestion(sid)["automation_id"]
        run(savi.handle_ha_event("automation_triggered", {"entity_id": entity}))
    clock.now = start + 600
    run(savi.handle_ha_event("state_changed", _changed("binary_sensor.movimiento_cocina", "on")))
    clock.now = start + 5 * 3600  # 07:00
    savi.tick()
    by_sid = {r["suggestion_id"]: r for r in store.savings("cerrado")}
    assert by_sid[d2]["hours"] == pytest.approx(600 / 3600, abs=1e-4)
    assert by_sid[d3]["hours"] == 4.0 and by_sid[d3]["kwh"] == 0.6  # 02:00 → 06:00


def test_return_before_one_minute(store):
    clock = Clock(NOW)
    savi, _ = make(store, FakeHa(), Tariff(800, True), clock)
    sid = d1(store)
    run(savi.approve(sid))
    _on(savi, "switch.tv_sala", 90)
    trigger(savi, sid)
    clock.now += 30
    run(savi.handle_ha_event("state_changed", _changed("binary_sensor.casa_ocupada", "on")))
    (closed,) = store.savings("cerrado")
    # 90 W × (30/3600) h / 1000 = 0.00075 kWh → 0.6 COP → rounds to 1 COP.
    assert closed["kwh"] == 0.0008 and closed["cop"] == 1


def test_ahorro_endpoint_and_sensor_values(store):
    clock = Clock(NOW)
    savi, _ = make(store, FakeHa(), Tariff(800, False), clock)
    sid = d1(store)
    d1_other = d1(store)  # pending
    run(savi.approve(sid))
    body = TestClient(create_app(savi, _probe)).get("/api/ahorro").json()
    assert body["formula"].startswith("kWh = Σ potencia × horas / 1000")
    assert "máximo de 8 h" in body["supuesto"]
    assert body["proyectado_mensual"]["kwh"] == 55.46
    assert "tarifa sin verificar" in body["etiquetas"]
    values = savi.sensor_values()
    assert values == {
        "savi_energia_evitada": 0.0,
        "savi_ahorro_estimado": 0,
        "savi_ahorro_mensual_proyectado": round(55.46 * 800),
        "savi_automatizaciones_activas": 1,
        "savi_sugerencias_pendientes": 1,
    }
    assert d1_other
