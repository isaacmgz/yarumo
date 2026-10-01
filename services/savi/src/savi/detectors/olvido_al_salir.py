"""D1 · olvido_al_salir: devices left ON when the last person leaves."""

from __future__ import annotations

from ..catalog import DEVICES, OCCUPANCY, OFF, ON
from .base import WINDOW_DAYS, Context, Proposal, per_month
from .timeline import Timeline, median

NAME = "olvido_al_salir"
MIN_DEPARTURES = 5
MIN_FREQUENCY = 0.5
HIGH_CONFIDENCE = 0.75
LEFT_ON_CHECK_S = 120  # "o se quedaron ON 2 min después"


def detect(ctx: Context) -> list[Proposal]:
    occupancy: Timeline | None = ctx.timelines.get(OCCUPANCY)
    if occupancy is None:
        return []
    changes = occupancy.transitions(ctx.window_start, ctx.now)
    departures = [(t, syn) for t, old, new, syn in changes if old == ON and new == OFF]
    if len(departures) < MIN_DEPARTURES:
        return []

    absences_h: list[float] = []
    left_on: dict[str, list[float]] = {d.entity_id: [] for d in DEVICES}
    synthetic = False
    for t, syn in departures:
        synthetic |= syn
        back = next((tt for tt, _, new, _ in changes if tt > t and new == ON), None)
        if back is not None:
            absences_h.append((back - t) / 3600)
        for d in DEVICES:
            tl = ctx.timelines.get(d.entity_id)
            if tl is not None and tl.state_at(t + LEFT_ON_CHECK_S) == ON:
                left_on[d.entity_id].append(t)

    n = len(departures)
    passing = [d for d in DEVICES if len(left_on[d.entity_id]) / n >= MIN_FREQUENCY]
    if not passing:
        return []

    median_h = round(median(absences_h), 2)
    departures_month = per_month(n)
    devices_ev = []
    lines = []
    total_kwh = 0.0
    for d in passing:
        k = len(left_on[d.entity_id])
        dev_kwh = d.power_w * (k / n) * median_h * departures_month / 1000
        total_kwh += dev_kwh
        devices_ev.append(
            {
                "entity_id": d.entity_id,
                "nombre": d.name,
                "potencia_w": d.power_w,
                "salidas_encendido": k,
                "frecuencia": round(k / n, 3),
            }
        )
        lines.append(
            f"{d.entity_id}: {d.power_w:g} W × ({k}/{n}) × {median_h:g} h × "
            f"({n} × 30/14) / 1000 = {dev_kwh:.2f} kWh"
        )

    example_ts = sorted({t for d in passing for t in left_on[d.entity_id]})[-3:]
    min_freq = min(len(left_on[d.entity_id]) / n for d in passing)
    names = " y ".join(d.name for d in passing)
    detail = "; ".join(f"{d.name}: {len(left_on[d.entity_id])} de {n} salidas" for d in passing)
    return [
        Proposal(
            detector=NAME,
            title="Apagar lo que queda encendido al salir",
            entities=sorted(d.entity_id for d in passing),
            evidence={
                "ventana_dias": WINDOW_DAYS,
                "salidas": n,
                "dispositivos": devices_ev,
                "fechas_ejemplo": [ctx.local(t).date().isoformat() for t in example_ts],
                "mediana_horas_ausencia": median_h,
                "salidas_mes": round(departures_month, 3),
                "datos_simulados": synthetic,
                "formula": "kWh_mes = Σ potencia × frecuencia × mediana_horas_ausencia × "
                "salidas_mes / 1000; salidas_mes = salidas × 30 / 14",
                "calculo": lines,
                "resumen": detail,
            },
            est_kwh_month=round(total_kwh, 2),
            confidence="alta" if min_freq >= HIGH_CONFIDENCE else "media",
            explanation=(
                f"Cuando la casa queda sola, muchas veces se queda prendido {names} "
                f"({detail}). Puedo apagarlos apenas salga el último."
            ),
        )
    ]
