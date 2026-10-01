"""Suggestion lifecycle, tariff handling and the HTTP API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from savi.api import Savi, create_app
from savi.suggestions import Tariff

from .conftest import END, TZ

NOW = END.timestamp() + 12 * 3600  # noon of the day after the seeded history


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


async def _probe() -> dict:
    return {"ha_ws": "connected"}


UNSET = Tariff(0, False)


def _client(store, tariff=UNSET, demo=True, clock=None):
    savi = Savi(store, TZ, tariff, clock or Clock(NOW), demo)
    return savi, TestClient(create_app(savi, _probe))


def test_seed_then_run_twice_does_not_duplicate(store):
    savi, client = _client(store)
    r = client.post("/admin/seed", params={"days": 21, "seed": 42})
    assert r.status_code == 200
    body = r.json()
    assert body["synthetic"] == 1 and body["hasta"] == END.isoformat()
    assert store.count_events(synthetic=True) == body["eventos"] > 0

    first = client.post("/api/detectores/run").json()
    after_first = client.get("/api/sugerencias").json()
    second = client.post("/api/detectores/run").json()
    after_second = client.get("/api/sugerencias").json()

    assert first["creadas"] == len(after_first) >= 4
    assert second["creadas"] == 0 and second["actualizadas"] == len(after_first)
    assert [s["id"] for s in after_second] == [s["id"] for s in after_first]
    assert {s["detector"] for s in after_second} >= {"olvido_al_salir", "plancha_olvidada"}

    # Re-seeding replaces the synthetic history instead of doubling it.
    again = client.post("/admin/seed", params={"days": 21, "seed": 42}).json()
    assert again["eventos_sinteticos_reemplazados"] == body["eventos"]
    assert store.count_events(synthetic=True) == body["eventos"]


def test_every_suggestion_has_evidence_and_traceable_saving(store):
    savi, client = _client(store)
    client.post("/admin/seed")
    client.post("/api/detectores/run")
    for s in client.get("/api/sugerencias").json():
        assert s["evidencia"]["formula"]
        if s["detector"] != "plancha_olvidada":
            assert s["ahorro_mensual_estimado"]["kwh"] > 0
            assert "datos simulados" in s["etiquetas"]
    d1 = next(
        s for s in client.get("/api/sugerencias").json() if s["detector"] == "olvido_al_salir"
    )
    ev = d1["evidencia"]
    by_hand = sum(
        d["potencia_w"]
        * (d["salidas_encendido"] / ev["salidas"])
        * ev["mediana_horas_ausencia"]
        * (ev["salidas"] * 30 / 14)
        / 1000
        for d in ev["dispositivos"]
    )
    assert d1["ahorro_mensual_estimado"]["kwh"] == pytest.approx(by_hand, abs=0.005)


def test_unverified_zero_tariff_shows_no_pesos(store):
    _, client = _client(store, Tariff(0, False))
    client.post("/admin/seed")
    client.post("/api/detectores/run")
    d1 = next(
        s for s in client.get("/api/sugerencias").json() if s["detector"] == "olvido_al_salir"
    )
    assert d1["ahorro_mensual_estimado"]["cop"] is None
    assert "tarifa sin verificar" in d1["etiquetas"]
    assert "tarifa sin verificar" in client.get("/panel").text


def test_verified_tariff_prices_kwh_and_drops_the_label(store):
    _, client = _client(store, Tariff(921.38, True))
    client.post("/admin/seed")
    client.post("/api/detectores/run")
    for s in client.get("/api/sugerencias").json():
        assert "tarifa sin verificar" not in s["etiquetas"]
        kwh = s["ahorro_mensual_estimado"]["kwh"]
        if kwh is not None:
            assert s["ahorro_mensual_estimado"]["cop"] == round(kwh * 921.38)
    assert "tarifa sin verificar" not in client.get("/panel").text


def test_unverified_positive_tariff_prices_and_keeps_the_label():
    t = Tariff(921.38, False)
    assert t.cop(10.0) == 9214 and t.labels == ["tarifa sin verificar"]


def test_rejected_suggestion_is_not_proposed_again_for_14_days(store):
    clock = Clock(NOW)
    savi, client = _client(store, clock=clock)
    client.post("/admin/seed")
    client.post("/api/detectores/run")
    r1 = next(
        s for s in client.get("/api/sugerencias").json() if s["detector"] == "plancha_olvidada"
    )
    assert client.post(f"/api/sugerencias/{r1['id']}/rechazar").json()["estado"] == "rechazada"

    clock.now += 13 * 86400
    assert client.post("/api/detectores/run").json()["omitidas_por_rechazo"] >= 1
    assert (
        sum(s["detector"] == "plancha_olvidada" for s in client.get("/api/sugerencias").json()) == 1
    )

    clock.now += 2 * 86400
    client.post("/api/detectores/run")
    r1s = [s for s in client.get("/api/sugerencias").json() if s["detector"] == "plancha_olvidada"]
    assert [s["estado"] for s in r1s] == ["rechazada", "nueva"]


def test_admin_requires_demo_mode_and_health_and_stubs(store):
    _, client = _client(store, demo=False)
    assert client.post("/admin/seed").status_code == 403
    assert client.get("/health").json() == {"ok": True, "ha_ws": "connected"}
    assert client.post("/api/sugerencias/999/aprobar").status_code == 404
    assert client.post("/api/sugerencias/999/rechazar").status_code == 404
    assert "Savi" in client.get("/panel").text
