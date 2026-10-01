"""HTTP API (docs/05-savi-ia.md §7) and the minimal H3 panel."""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import detectors, seed, suggestions
from .store import Store
from .suggestions import Tariff


class Savi:
    """Application core shared by the API, the hourly loop and the tests."""

    def __init__(
        self,
        store: Store,
        tz: ZoneInfo,
        tariff: Tariff,
        clock: Callable[[], float],
        demo_mode: bool = True,
    ) -> None:
        self.store = store
        self.tz = tz
        self.tariff = tariff
        self.clock = clock
        self.demo_mode = demo_mode
        self.last_run: dict | None = None

    def run_detectors(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        proposals = detectors.run_all(self.store, now, self.tz)
        result = suggestions.apply(self.store, proposals, now, self.tariff)
        self.last_run = {"at": self._iso(now), **result}
        return self.last_run

    def seed(self, days: int, seed_value: int) -> dict:
        today = datetime.fromtimestamp(self.clock(), self.tz).date()
        end = datetime.combine(today, time(0), self.tz)  # "terminando ayer a medianoche"
        removed = self.store.delete_synthetic_events()
        events = seed.generate(days, seed_value, end)
        self.store.add_events(events)
        return {
            "eventos": len(events),
            "eventos_sinteticos_reemplazados": removed,
            "desde": (end - timedelta(days=days)).isoformat(),
            "hasta": end.isoformat(),
            "semilla": seed_value,
            "dias": days,
            "synthetic": 1,
        }

    def _iso(self, ts: float | None) -> str | None:
        return None if ts is None else datetime.fromtimestamp(ts, self.tz).isoformat()

    def view(self, s: dict) -> dict:
        labels = ["estimado"] + self.tariff.labels
        if s["evidence"].get("datos_simulados"):
            labels.insert(0, "datos simulados")
        return {
            "id": s["id"],
            "detector": s["detector"],
            "titulo": s["title"],
            "explicacion": s["explanation"],
            "entidades": s["entities"],
            "estado": s["status"],
            "confianza": s["confidence"],
            "evidencia": s["evidence"],
            "ahorro_mensual_estimado": {
                "kwh": s["est_kwh_month"],
                "cop": s["est_cop_month"],
                "tarifa_cop_kwh": self.tariff.cop_kwh or None,
                "tarifa_verificada": self.tariff.verified,
            },
            "etiquetas": labels,
            "creada": self._iso(s["created_at"]),
            "actualizada": self._iso(s["updated_at"]),
            "decidida": self._iso(s["decided_at"]),
            "decidida_por": s["decided_via"],
            "automation_id": s["automation_id"],
        }

    def list_views(self) -> list[dict]:
        return [self.view(s) for s in self.store.suggestions()]


def create_app(
    savi: Savi,
    health_probe: Callable[[], Awaitable[dict]],
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    app = FastAPI(title="savi", lifespan=lifespan)

    def _demo_only() -> None:
        if not savi.demo_mode:
            raise HTTPException(403, "Esto solo funciona con DEMO_MODE=true.")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, **(await health_probe())}

    @app.get("/api/sugerencias")
    def list_suggestions() -> list[dict]:
        return savi.list_views()

    @app.get("/api/sugerencias/{suggestion_id}")
    def get_suggestion(suggestion_id: int) -> dict:
        s = savi.store.get_suggestion(suggestion_id)
        if s is None:
            raise HTTPException(404, "No encuentro esa sugerencia.")
        return savi.view(s)

    @app.post("/api/sugerencias/{suggestion_id}/rechazar")
    def reject(suggestion_id: int) -> dict:
        s = suggestions.reject(savi.store, suggestion_id, savi.clock())
        if s is None:
            raise HTTPException(404, "No encuentro esa sugerencia.")
        return savi.view(s)

    @app.post("/api/sugerencias/{suggestion_id}/aprobar")
    @app.post("/api/sugerencias/{suggestion_id}/desactivar")
    def not_yet(suggestion_id: int) -> dict:
        raise HTTPException(501, "Crear y desactivar automatizaciones llega en el hito H4.")

    @app.post("/api/detectores/run")
    def run_detectors() -> dict:
        return savi.run_detectors()

    @app.post("/admin/seed")
    def admin_seed(
        days: int = Query(21, ge=1, le=60),
        seed: int = Query(42),  # noqa: B008
    ) -> dict:
        _demo_only()
        return savi.seed(days, seed)

    @app.post("/admin/reset")
    def admin_reset() -> dict:
        _demo_only()
        return {
            "sugerencias_borradas": savi.store.delete_suggestions(),
            "eventos_sinteticos_borrados": savi.store.delete_synthetic_events(),
        }

    @app.get("/panel", response_class=HTMLResponse)
    def panel() -> str:
        return render_panel(savi.list_views(), savi.tariff)

    return app


def _money(view: dict) -> str:
    a = view["ahorro_mensual_estimado"]
    if a["kwh"] is None:
        return "Sin estimado mensual (regla de seguridad)."
    text = f"{a['kwh']:g} kWh al mes (estimado)"
    if a["cop"] is None:
        return text + " · en pesos: sin tarifa definida (tarifa sin verificar)"
    mark = "" if a["tarifa_verificada"] else " (tarifa sin verificar)"
    return text + f" · ${a['cop']:,.0f} COP al mes{mark}".replace(",", ".")


def render_panel(views: list[dict], tariff: Tariff) -> str:
    e = html.escape
    items = []
    for v in views:
        ev = v["evidencia"]
        calc = "".join(f"<li><code>{e(line)}</code></li>" for line in ev.get("calculo", []))
        items.append(
            f"<li><h3>{e(v['titulo'])}</h3>"
            f"<p>{e(v['explicacion'])}</p>"
            f"<p>Evidencia: {e(str(ev.get('resumen', ev.get('origen', ''))))}</p>"
            f"<p>Ahorro: {e(_money(v))}</p>"
            f"<p>Confianza: {e(v['confianza'])} · Estado: {e(v['estado'])}"
            f" · Etiquetas: {e(', '.join(v['etiquetas']))}</p>"
            f"<details><summary>¿Cómo se calcula?</summary><p>{e(ev.get('formula', ''))}</p>"
            f"<ul>{calc}</ul></details></li>"
        )
    body = "".join(items) or "<li>Todavía no he encontrado nada para proponer.</li>"
    tariff_note = (
        "Tarifa sin definir: muestro solo kWh (tarifa sin verificar)."
        if tariff.cop_kwh <= 0
        else f"Tarifa: {tariff.cop_kwh:g} COP/kWh"
        + ("" if tariff.verified else " (tarifa sin verificar)")
    )
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Savi</title></head><body>"
        "<h1>Savi</h1><p>Lo que he aprendido de la casa. Los ahorros son estimados.</p>"
        f"<p>{e(tariff_note)}</p><ol>{body}</ol></body></html>"
    )
