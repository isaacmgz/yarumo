"""Actionable notifications to notify.residentes and parsing of the phones' answers.

docs/04-home-assistant.md "Notificaciones": actions `SAVI_APROBAR::<id>` / `SAVI_RECHAZAR::<id>`;
tapping one makes HA fire `mobile_app_notification_action`, which Savi hears on its WebSocket.
"""

from __future__ import annotations

from typing import Any

APPROVE = "SAVI_APROBAR"
REJECT = "SAVI_RECHAZAR"
VERBS = {APPROVE: "aprobar", REJECT: "rechazar"}


def tag(suggestion_id: int) -> str:
    return f"savi_sugerencia_{suggestion_id}"


def suggestion_message(s: dict) -> dict[str, Any]:
    """notify.residentes service data for a new suggestion."""
    sid = s["id"]
    return {
        "title": f"Savi · {s['title']}",
        "message": s["explanation"],
        "data": {
            "tag": tag(sid),
            "actions": [
                {"action": f"{APPROVE}::{sid}", "title": "Activar"},
                {"action": f"{REJECT}::{sid}", "title": "Ahora no"},
            ],
        },
    }


def parse_action(data: dict[str, Any]) -> tuple[str, int] | None:
    """`mobile_app_notification_action` data → ("aprobar" | "rechazar", suggestion_id).

    Android sends `action`; older iOS payloads use `actionName`.
    """
    raw = data.get("action") or data.get("actionName") or ""
    prefix, sep, rest = str(raw).partition("::")
    if not sep or prefix not in VERBS or not rest.isdigit():
        return None
    return VERBS[prefix], int(rest)
