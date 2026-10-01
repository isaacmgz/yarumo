"""Avoided energy (docs/05-savi-ia.md §5). Deterministic; the LLM never computes this.

Counterfactual: if Savi had not turned the device off, it would have stayed on until someone
came back, with a maximum of 8 h. kWh = Σ power × hours / 1000 · COP = kWh × TARIFA_COP_KWH.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .catalog import DEVICES_BY_ID, MOTION_BY_ROOM, OCCUPANCY, ON
from .store import Store
from .suggestions import Tariff

MAX_HOURS = 8.0
NIGHT_END = time(6, 0)  # D3 closes at 06:00
FORMULA = "kWh = Σ potencia × horas / 1000 · COP = kWh × TARIFA_COP_KWH · horas ≤ 8"
ASSUMPTION = (
    "Si Savi no hubiera apagado, el dispositivo habría seguido encendido hasta que alguien "
    "volviera, con un máximo de 8 h. Las potencias son los supuestos nominales del contrato."
)


def avoided_hours(started_at: float, ended_at: float) -> float:
    return min(max(ended_at - started_at, 0.0), MAX_HOURS * 3600) / 3600


def compute(power_w: float, started_at: float, ended_at: float, tariff: Tariff) -> dict:
    hours = avoided_hours(started_at, ended_at)
    kwh = power_w * hours / 1000
    return {"hours": round(hours, 4), "kwh": round(kwh, 4), "cop": tariff.cop(kwh)}


def _power(entity_id: str, cache: dict[str, dict]) -> float:
    """Last cached power reading while ON; the nominal contract power if there is none."""
    nominal = DEVICES_BY_ID[entity_id].power_w
    raw = (cache.get(f"sensor.{DEVICES_BY_ID[entity_id].object_id}_potencia") or {}).get("state")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return nominal
    return value if value > 0 else nominal


class Savings:
    def __init__(self, store: Store, tariff: Tariff, tz: ZoneInfo) -> None:
        self.store = store
        self.tariff = tariff
        self.tz = tz

    def open(self, suggestion: dict, cache: dict[str, dict], now: float) -> int | None:
        """A Savi automation fired: record what was ON. None if nothing was on or one is open."""
        if any(r["suggestion_id"] == suggestion["id"] for r in self.store.savings("en_curso")):
            return None
        devices = [
            {
                "entity_id": e,
                "nombre": DEVICES_BY_ID[e].name,
                "potencia_w": _power(e, cache),
            }
            for e in suggestion["entities"]
            if e in DEVICES_BY_ID and (cache.get(e) or {}).get("state") == ON
        ]
        if not devices:
            return None
        power = round(sum(d["potencia_w"] for d in devices), 2)
        return self.store.open_saving(suggestion["id"], now, devices, power)

    def _end_trigger(self, detector: str, entities: list[str]) -> str | None:
        if detector in ("olvido_al_salir", "plancha_olvidada"):
            return OCCUPANCY
        if detector == "luz_sin_movimiento" and entities and entities[0] in DEVICES_BY_ID:
            return MOTION_BY_ROOM[DEVICES_BY_ID[entities[0]].room]
        return None

    def _close(self, record: dict, ended_at: float) -> None:
        ended_at = min(ended_at, record["started_at"] + MAX_HOURS * 3600)
        c = compute(record["power_w"], record["started_at"], ended_at, self.tariff)
        self.store.close_saving(record["id"], ended_at, c["hours"], c["kwh"], c["cop"])

    def on_state_changed(self, entity_id: str, new_state: str | None, ts: float) -> list[int]:
        """Close open records whose end event is this one (D1/R1: house occupied; D2: motion)."""
        if new_state != ON:
            return []
        closed = []
        for r in self.store.savings("en_curso"):
            s = self.store.get_suggestion(r["suggestion_id"])
            if s and self._end_trigger(s["detector"], s["entities"]) == entity_id:
                self._close(r, ts)
                closed.append(r["id"])
        return closed

    def _night_end(self, started_at: float) -> float:
        start = datetime.fromtimestamp(started_at, self.tz)
        end = datetime.combine(start.date(), NIGHT_END, self.tz)
        if end <= start:
            end = datetime.combine(start.date() + timedelta(days=1), NIGHT_END, self.tz)
        return end.timestamp()

    def tick(self, now: float) -> list[int]:
        """Close records that hit the 8 h cap, and D3 records at 06:00."""
        closed = []
        for r in self.store.savings("en_curso"):
            deadline = r["started_at"] + MAX_HOURS * 3600
            s = self.store.get_suggestion(r["suggestion_id"])
            if s and s["detector"] == "consumo_nocturno":
                deadline = min(deadline, self._night_end(r["started_at"]))
            if now >= deadline:
                self._close(r, deadline)
                closed.append(r["id"])
        return closed

    # ---- views ----------------------------------------------------------

    def _iso(self, ts: float | None) -> str | None:
        return None if ts is None else datetime.fromtimestamp(ts, self.tz).isoformat()

    def view(self, r: dict, now: float) -> dict:
        if r["status"] == "en_curso":
            c = compute(r["power_w"], r["started_at"], now, self.tariff)
        else:
            c = {"hours": r["hours"], "kwh": r["kwh"], "cop": r["cop"]}
        calc = f"{r['power_w']:g} W × {c['hours']:g} h / 1000 = {c['kwh']:g} kWh"
        if c["cop"] is not None:
            calc += f" × {self.tariff.cop_kwh:g} COP/kWh = {c['cop']:g} COP"
        return {
            "id": r["id"],
            "sugerencia_id": r["suggestion_id"],
            "estado": r["status"],
            "desde": self._iso(r["started_at"]),
            "hasta": self._iso(r["ended_at"]),
            "dispositivos": r["devices"],
            "potencia_w": r["power_w"],
            "horas": c["hours"],
            "kwh": c["kwh"],
            "cop": c["cop"],
            "calculo": calc,
        }

    def totals(self, now: float) -> dict:
        views = [self.view(r, now) for r in self.store.savings()]
        kwh = round(sum(v["kwh"] for v in views), 4)
        return {
            "kwh": kwh,
            "cop": self.tariff.cop(kwh),
            "registros": views,
        }
