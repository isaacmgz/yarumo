"""R1 · plancha_olvidada: a factory safety rule, not learned from patterns."""

from __future__ import annotations

from ..catalog import DEVICES_BY_ID, IRON, OCCUPANCY
from .base import Context, Proposal

NAME = "plancha_olvidada"


def detect(_: Context) -> list[Proposal]:
    iron = DEVICES_BY_ID[IRON]
    return [
        Proposal(
            detector=NAME,
            title="Apagar la plancha si la casa queda sola",
            entities=[IRON],
            evidence={
                "origen": "regla de seguridad de fábrica (no aprendida)",
                "disparadores": [
                    f"{OCCUPANCY} pasa a off con {IRON} encendida",
                    f"{IRON} se enciende con la casa vacía",
                ],
                "potencia_w": iron.power_w,
                "datos_simulados": False,
                "formula": "Sin estimado mensual: es una regla de seguridad y la plancha no se "
                "ha olvidado en el historial.",
            },
            est_kwh_month=None,
            confidence="alta",
            explanation=(
                "Esta no la aprendí, la traigo de fábrica: si la plancha queda prendida y no hay "
                "nadie en casa, la apago de inmediato y les aviso."
            ),
        )
    ]
