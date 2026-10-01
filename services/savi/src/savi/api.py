"""HTTP API (docs/05-savi-ia.md §7), the H4 actions (approve, notify, savings) and the panel."""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import automations, detectors, notifications, savings, seed, suggestions
from .ha_client import HaClient, HaError
from .store import Store
from .suggestions import Tariff

log = logging.getLogger("savi.core")

PENDING = ("nueva", "notificada")
Via = Literal["panel", "celular", "chat"]


class ActionError(RuntimeError):
    """An action that could not be completed; the message is user-facing (Spanish)."""


class Savi:
    """Application core shared by the API, the background loops and the tests."""

    def __init__(
        self,
        store: Store,
        tz: ZoneInfo,
        tariff: Tariff,
        clock: Callable[[], float],
        demo_mode: bool = True,
        ha: HaClient | None = None,
        cache: dict[str, dict] | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self.tz = tz
        self.tariff = tariff
        self.clock = clock
        self.demo_mode = demo_mode
        self.ha = ha
        self.cache = cache if cache is not None else {}
        self.on_change = on_change or (lambda: None)
        self.savings = savings.Savings(store, tariff, tz)
        self.last_run: dict | None = None
        self._lock = asyncio.Lock()

    # ---- H4: acting in Home Assistant -------------------------------------

    def _require_ha(self) -> HaClient:
        if self.ha is None:
            raise ActionError("No tengo conexión con Home Assistant (falta HA_TOKEN).")
        return self.ha

    def _get(self, suggestion_id: int) -> dict:
        s = self.store.get_suggestion(suggestion_id)
        if s is None:
            raise LookupError(suggestion_id)
        return s

    async def tell(self, message: str, title: str = "Savi", data: dict | None = None) -> bool:
        """Push to notify.residentes and leave a persistent_notification (works offline)."""
        if self.ha is None:
            return False
        delivered = False
        payload = {"title": title, "message": message, **({"data": data} if data else {})}
        try:
            await self.ha.call_service("notify", "residentes", payload)
            delivered = True
        except HaError as exc:
            log.warning("push failed: %s", exc)
        try:
            pn = {"title": title, "message": message}
            if data and data.get("tag"):
                pn["notification_id"] = data["tag"]
            await self.ha.call_service("persistent_notification", "create", pn)
            delivered = True
        except HaError as exc:
            log.warning("persistent_notification failed: %s", exc)
        return delivered

    async def approve(self, suggestion_id: int, via: str = "panel") -> dict:
        async with self._lock:
            s = self._get(suggestion_id)
            if s["status"] == "activa":
                return s
            ha = self._require_ha()
            now = self.clock()
            try:
                config = automations.build(s, now, self.tz)
            except ValueError as exc:
                raise ActionError("No sé cómo crear esa automatización.") from exc
            self.store.set_suggestion_status(suggestion_id, "aprobada", now, via)
            aid = automations.automation_id(suggestion_id)
            try:
                method = await ha.create_automation(aid, config)
                entity_id = await ha.wait_for_automation(aid)
                if entity_id is None:
                    raise HaError(f"{aid} not found in /api/states after creation")
                await ha.call_service("automation", "turn_on", {"entity_id": entity_id})
            except HaError as exc:
                log.error("could not create %s: %s", aid, exc)
                raise ActionError(
                    "No pude crear la automatización en Home Assistant. Quedó aprobada; "
                    "inténtalo de nuevo en un momento."
                ) from exc
            log.info("automation %s created via %s as %s", aid, method, entity_id)
            self.store.set_automation_id(suggestion_id, entity_id)
            self.store.set_suggestion_status(suggestion_id, "activa", self.clock(), via)
        await self.tell(
            "Listo, ya quedó. Te cuento cuando actúe.",
            data={"tag": notifications.tag(suggestion_id)},
        )
        self.on_change()
        return self._get(suggestion_id)

    async def deactivate(self, suggestion_id: int, via: str = "panel") -> dict:
        s = self._get(suggestion_id)
        if s["automation_id"]:
            try:
                await self._require_ha().call_service(
                    "automation", "turn_off", {"entity_id": s["automation_id"]}
                )
            except HaError as exc:
                raise ActionError("No pude apagar la automatización en Home Assistant.") from exc
        self.store.set_suggestion_status(suggestion_id, "desactivada", self.clock(), via)
        self.on_change()
        return self._get(suggestion_id)

    async def reject(self, suggestion_id: int, via: str = "panel") -> dict:
        s = suggestions.reject(self.store, suggestion_id, self.clock(), via)
        if s is None:
            raise LookupError(suggestion_id)
        if via == "celular":
            await self.tell(
                "Listo, no la activo. No te la vuelvo a proponer en 14 días.",
                data={"tag": notifications.tag(suggestion_id)},
            )
        self.on_change()
        return s

    async def notify_suggestion(self, suggestion_id: int) -> dict:
        s = self._get(suggestion_id)
        self._require_ha()
        msg = notifications.suggestion_message(s)
        if not await self.tell(msg["message"], msg["title"], msg["data"]):
            raise ActionError("No pude enviar la notificación.")
        if s["status"] == "nueva":
            self.store.set_status(suggestion_id, "notificada", self.clock())
        self.on_change()
        return self._get(suggestion_id)

    async def notify_new(self) -> int:
        """Send one actionable notification per suggestion still `nueva`."""
        if self.ha is None:
            return 0
        sent = 0
        for s in self.store.suggestions():
            if s["status"] == "nueva":
                try:
                    await self.notify_suggestion(s["id"])
                    sent += 1
                except ActionError:
                    log.warning("could not notify suggestion %s", s["id"])
        return sent

    async def handle_ha_event(self, event_type: str, data: dict) -> None:
        """Listener for the ingest WebSocket (runs after the state cache is updated)."""
        now = self.clock()
        if event_type == "mobile_app_notification_action":
            parsed = notifications.parse_action(data)
            if parsed is None:
                return
            verb, sid = parsed
            try:
                if verb == "aprobar":
                    await self.approve(sid, via="celular")
                else:
                    await self.reject(sid, via="celular")
            except LookupError:
                log.warning("notification action for unknown suggestion %s", sid)
            except ActionError as exc:
                await self.tell(str(exc))
        elif event_type == "automation_triggered":
            s = self.store.suggestion_by_automation(data.get("entity_id", ""))
            if s and s["status"] == "activa" and self.savings.open(s, self.cache, now):
                self.on_change()
        elif event_type == "state_changed":
            new = data.get("new_state") or {}
            if self.savings.on_state_changed(data.get("entity_id", ""), new.get("state"), now):
                self.on_change()

    def tick(self, now: float | None = None) -> list[int]:
        closed = self.savings.tick(self.clock() if now is None else now)
        if closed:
            self.on_change()
        return closed

    # ---- H4: what Savi counts ---------------------------------------------

    def ahorro(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        totals = self.savings.totals(now)
        records = totals["registros"]
        active = [s for s in self.store.suggestions() if s["status"] == "activa"]
        proj_kwh = round(sum(s["est_kwh_month"] or 0 for s in active), 3)
        labels = ["estimado"] + self.tariff.labels
        if any(s["evidence"].get("datos_simulados") for s in active):
            labels.insert(0, "datos simulados")
        return {
            "acumulado": {"kwh": totals["kwh"], "cop": totals["cop"]},
            "en_curso": [r for r in records if r["estado"] == "en_curso"],
            "cerrados": [r for r in records if r["estado"] == "cerrado"],
            "proyectado_mensual": {
                "kwh": proj_kwh,
                "cop": self.tariff.cop(proj_kwh),
                "sugerencias_activas": [s["id"] for s in active],
                "nota": "Suma del ahorro mensual estimado de las automatizaciones activas.",
            },
            "formula": savings.FORMULA,
            "supuesto": savings.ASSUMPTION,
            "tarifa": {"cop_kwh": self.tariff.cop_kwh or None, "verificada": self.tariff.verified},
            "etiquetas": labels,
        }

    def sensor_values(self, now: float | None = None) -> dict[str, float | int | None]:
        a = self.ahorro(now)
        statuses = [s["status"] for s in self.store.suggestions()]
        return {
            "savi_energia_evitada": a["acumulado"]["kwh"],
            "savi_ahorro_estimado": a["acumulado"]["cop"],
            "savi_ahorro_mensual_proyectado": a["proyectado_mensual"]["cop"],
            "savi_automatizaciones_activas": statuses.count("activa"),
            "savi_sugerencias_pendientes": sum(st in PENDING for st in statuses),
        }

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

    async def _act(action: Callable[..., Awaitable[dict]], suggestion_id: int, via: str) -> dict:
        try:
            return savi.view(await action(suggestion_id, via))
        except LookupError as exc:
            raise HTTPException(404, "No encuentro esa sugerencia.") from exc
        except ActionError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/sugerencias/{suggestion_id}/rechazar")
    async def reject(suggestion_id: int, via: Via = "panel") -> dict:
        return await _act(savi.reject, suggestion_id, via)

    @app.post("/api/sugerencias/{suggestion_id}/aprobar")
    async def approve(suggestion_id: int, via: Via = "panel") -> dict:
        return await _act(savi.approve, suggestion_id, via)

    @app.post("/api/sugerencias/{suggestion_id}/desactivar")
    async def deactivate(suggestion_id: int, via: Via = "panel") -> dict:
        return await _act(savi.deactivate, suggestion_id, via)

    @app.post("/api/sugerencias/{suggestion_id}/notificar")
    async def notify(suggestion_id: int) -> dict:
        return await _act(lambda sid, _via: savi.notify_suggestion(sid), suggestion_id, "")

    @app.get("/api/ahorro")
    def ahorro() -> dict:
        return savi.ahorro()

    @app.post("/api/detectores/run")
    async def run_detectors() -> dict:
        result = await asyncio.to_thread(savi.run_detectors)
        notified = await savi.notify_new()
        savi.on_change()
        return {**result, "notificadas": notified}

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
            "ahorros_borrados": savi.store.delete_savings(),
        }

    @app.get("/panel", response_class=HTMLResponse)
    def panel() -> str:
        return render_panel(savi.list_views(), savi.tariff, savi.ahorro())

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


_BUTTONS = {
    "nueva": (("aprobar", "Activar"), ("rechazar", "Ahora no")),
    "notificada": (("aprobar", "Activar"), ("rechazar", "Ahora no")),
    "aprobada": (("aprobar", "Reintentar"),),
    "activa": (("desactivar", "Desactivar"),),
    "desactivada": (("aprobar", "Activar de nuevo"),),
}
_SCRIPT = (
    "<script>async function act(id,a){const r=await fetch(`/api/sugerencias/${id}/${a}`,"
    "{method:'POST'});if(!r.ok){alert((await r.json()).detail||'No pude hacerlo.')}"
    "location.reload()}</script>"
)


def _savings_block(a: dict, tariff: Tariff) -> str:
    e = html.escape
    acc = a["acumulado"]
    text = f"{acc['kwh']:g} kWh evitados (estimado)"
    if acc["cop"] is not None:
        mark = "" if tariff.verified else " (tarifa sin verificar)"
        text += f" · ${acc['cop']:,.0f} COP{mark}".replace(",", ".")
    live = "".join(
        f"<li>En curso: {e(', '.join(d['nombre'] for d in r['dispositivos']))} · "
        f"<code>{e(r['calculo'])}</code></li>"
        for r in a["en_curso"]
    )
    closed = "".join(
        f"<li>{e(r['desde'][:16])} → {e((r['hasta'] or '')[11:16])}: <code>{e(r['calculo'])}</code>"
        "</li>"
        for r in a["cerrados"][-5:]
    )
    return (
        f"<h2>Lo que Savi ha evitado</h2><p><strong>{e(text)}</strong></p>"
        f"<ul>{live}{closed}</ul>"
        f"<details><summary>¿Cómo se calcula?</summary><p>{e(a['formula'])}</p>"
        f"<p>{e(a['supuesto'])}</p></details>"
    )


def render_panel(views: list[dict], tariff: Tariff, ahorro: dict | None = None) -> str:
    e = html.escape
    items = []
    for v in views:
        buttons = "".join(
            f"<button onclick=\"act({v['id']},'{a}')\">{label}</button> "
            for a, label in _BUTTONS.get(v["estado"], ())
        )
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
            f"<ul>{calc}</ul></details><p>{buttons}</p></li>"
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
        f"<title>Savi</title>{_SCRIPT}</head><body>"
        "<h1>Savi</h1><p>Lo que he aprendido de la casa. Los ahorros son estimados.</p>"
        f"<p>{e(tariff_note)}</p>{_savings_block(ahorro, tariff) if ahorro else ''}"
        f"<h2>Sugerencias</h2><ol>{body}</ol></body></html>"
    )
