"""HA automation templates per detector (docs/05-savi-ia.md §3 and docs/04 "Automatizaciones").

Pure functions: suggestion in, HA automation config (JSON-able dict) out.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .catalog import DEVICES_BY_ID, IRON, MOTION_BY_ROOM, OCCUPANCY


def automation_id(suggestion_id: int) -> str:
    return f"savi_{suggestion_id}"


def _names(entities: list[str]) -> str:
    names = [DEVICES_BY_ID[e].name if e in DEVICES_BY_ID else e for e in entities]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " y " + names[-1]


def _notify(message: str, high: bool = False) -> dict:
    data: dict = {"title": "Savi", "message": message}
    if high:
        data["data"] = {"priority": "high", "ttl": 0, "push": {"interruption-level": "critical"}}
    # A phone that cannot be reached must not stop the turn_off that already happened.
    return {"action": "notify.residentes", "continue_on_error": True, "data": data}


def _turn_off(entities: list[str]) -> dict:
    return {"action": "homeassistant.turn_off", "target": {"entity_id": list(entities)}}


def _description(s: dict, now: float, tz: ZoneInfo) -> str:
    ev = s["evidence"]
    summary = ev.get("resumen") or ev.get("origen") or ""
    date = datetime.fromtimestamp(now, tz).date().isoformat()
    return (
        f"Propuesta por Savi y aprobada el {date}. Evidencia: {summary}. "
        f"{s['explanation']} No editar a mano: se desactiva desde Savi o desde HA."
    )


def build(s: dict, now: float, tz: ZoneInfo) -> dict:
    """Automation config for an approved suggestion. Raises ValueError for unknown detectors."""
    entities = list(s["entities"])
    detector = s["detector"]
    if detector == "olvido_al_salir":
        triggers = [{"trigger": "state", "entity_id": OCCUPANCY, "to": "off"}]
        conditions: list[dict] = []
        actions = [
            _turn_off(entities),
            _notify(f"Nadie quedó en casa. Apagué {_names(entities)}."),
        ]
    elif detector == "luz_sin_movimiento":
        light = entities[0]
        motion = MOTION_BY_ROOM[DEVICES_BY_ID[light].room]
        triggers = [
            {"trigger": "state", "entity_id": motion, "to": "off", "for": {"minutes": 20}},
            {"trigger": "state", "entity_id": light, "to": "on", "for": {"minutes": 20}},
        ]
        conditions = [
            {"condition": "state", "entity_id": light, "state": "on"},
            {"condition": "state", "entity_id": motion, "state": "off", "for": {"minutes": 20}},
        ]
        actions = [_turn_off(entities)]
    elif detector == "consumo_nocturno":
        device = entities[0]
        motion = MOTION_BY_ROOM[DEVICES_BY_ID[device].room]
        triggers = [
            {"trigger": "time", "at": "01:00:00"},
            {"trigger": "state", "entity_id": motion, "to": "off", "for": {"minutes": 30}},
            {"trigger": "state", "entity_id": device, "to": "on", "for": {"minutes": 30}},
        ]
        conditions = [
            {"condition": "time", "after": "01:00:00", "before": "06:00:00"},
            {"condition": "state", "entity_id": device, "state": "on"},
            {"condition": "state", "entity_id": motion, "state": "off", "for": {"minutes": 30}},
        ]
        actions = [
            _turn_off(entities),
            _notify(f"Era de madrugada y nadie estaba cerca. Apagué {_names(entities)}."),
        ]
    elif detector == "plancha_olvidada":
        triggers = [
            {"trigger": "state", "entity_id": OCCUPANCY, "to": "off"},
            {"trigger": "state", "entity_id": IRON, "to": "on"},
        ]
        conditions = [
            {"condition": "state", "entity_id": OCCUPANCY, "state": "off"},
            {"condition": "state", "entity_id": IRON, "state": "on"},
        ]
        actions = [
            _turn_off([IRON]),
            _notify("La plancha estaba prendida y no hay nadie en casa. Ya la apagué.", True),
        ]
    else:
        raise ValueError(f"no automation template for detector {detector!r}")
    return {
        "alias": f"Savi · {s['title']}",
        "description": _description(s, now, tz),
        "mode": "single",
        "triggers": triggers,
        "conditions": conditions,
        "actions": actions,
    }
