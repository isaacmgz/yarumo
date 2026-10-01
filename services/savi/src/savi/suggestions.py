"""Suggestion lifecycle: deduplication, the 14-day respect for a "no", and pricing."""

from __future__ import annotations

from dataclasses import dataclass

from .detectors.base import Proposal
from .store import Store

REJECTION_COOLDOWN_S = 14 * 86400
STATUSES = ("nueva", "notificada", "aprobada", "activa", "rechazada", "desactivada")


@dataclass(frozen=True)
class Tariff:
    cop_kwh: float
    verified: bool

    def cop(self, kwh: float | None) -> float | None:
        """COP = kWh × tariff. Without a tariff (0) there is no money figure, never a zero."""
        if kwh is None or self.cop_kwh <= 0:
            return None
        return round(kwh * self.cop_kwh)

    @property
    def labels(self) -> list[str]:
        if self.cop_kwh <= 0:
            return ["tarifa sin definir", "tarifa sin verificar"]
        return [] if self.verified else ["tarifa sin verificar"]


def apply(store: Store, proposals: list[Proposal], now: float, tariff: Tariff) -> dict:
    """Upsert proposals. Same detector + same entity set updates instead of duplicating."""
    result = {"creadas": 0, "actualizadas": 0, "omitidas_por_rechazo": 0}
    for p in proposals:
        data = {
            "detector": p.detector,
            "dedup_key": p.dedup_key,
            "title": p.title,
            "entities": sorted(p.entities),
            "evidence": p.evidence,
            "est_kwh_month": p.est_kwh_month,
            "est_cop_month": tariff.cop(p.est_kwh_month),
            "confidence": p.confidence,
            "explanation": p.explanation,
        }
        existing = store.latest_suggestion(p.dedup_key)
        if existing is None:
            store.insert_suggestion(data, now)
            result["creadas"] += 1
        elif existing["status"] == "rechazada":
            if now - (existing["decided_at"] or 0) < REJECTION_COOLDOWN_S:
                result["omitidas_por_rechazo"] += 1
            else:
                store.insert_suggestion(data, now)
                result["creadas"] += 1
        else:
            store.update_suggestion_findings(existing["id"], data, now)
            result["actualizadas"] += 1
    return result


def reject(store: Store, suggestion_id: int, now: float, via: str = "panel") -> dict | None:
    s = store.get_suggestion(suggestion_id)
    if s is None:
        return None
    store.set_suggestion_status(suggestion_id, "rechazada", now, via)
    return store.get_suggestion(suggestion_id)
