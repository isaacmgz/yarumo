"""D2 · luz_sin_movimiento: a light ON, house occupied, no motion in its room for >= 20 min."""

from __future__ import annotations

from ..catalog import LIGHTS, MOTION_BY_ROOM, OCCUPANCY
from .base import WINDOW_DAYS, Context, Proposal, per_month
from .timeline import intersect, median, subtract

NAME = "luz_sin_movimiento"
QUIET_S = 20 * 60
MIN_EPISODES = 6


def detect(ctx: Context) -> list[Proposal]:
    occupancy = ctx.timelines.get(OCCUPANCY)
    if occupancy is None:
        return []
    ws, now = ctx.window_start, ctx.now
    occupied = occupancy.on_intervals(ws, now)
    out: list[Proposal] = []
    for light in LIGHTS:
        tl = ctx.timelines.get(light.entity_id)
        motion_tl = ctx.timelines.get(MOTION_BY_ROOM[light.room])
        if tl is None or motion_tl is None:
            continue
        lit = intersect(tl.on_intervals(ws, now), occupied)
        quiet = subtract(lit, motion_tl.on_intervals(ws, now))
        episodes = [(a, b) for a, b in quiet if b - a >= QUIET_S]
        if len(episodes) < MIN_EPISODES:
            continue
        # The automation waits 20 min without motion, so only the time after that is avoidable.
        avoidable_h = round(median([(b - a - QUIET_S) / 3600 for a, b in episodes]), 3)
        episodes_month = per_month(len(episodes))
        est = light.power_w * avoidable_h * episodes_month / 1000
        synthetic = any(tl.synthetic_in(a, b) or occupancy.synthetic_in(a, b) for a, b in episodes)
        out.append(
            Proposal(
                detector=NAME,
                title=f"Apagar {light.name} cuando nadie está ahí",
                entities=[light.entity_id],
                evidence={
                    "ventana_dias": WINDOW_DAYS,
                    "episodios": len(episodes),
                    "potencia_w": light.power_w,
                    "minutos_sin_movimiento_mediana": round(
                        median([(b - a) / 60 for a, b in episodes]), 1
                    ),
                    "mediana_horas_evitables": avoidable_h,
                    "episodios_mes": round(episodes_month, 3),
                    "fechas_ejemplo": [ctx.local(a).date().isoformat() for a, _ in episodes[-3:]],
                    "datos_simulados": synthetic,
                    "formula": "kWh_mes = potencia × mediana_horas_evitables × episodios_mes / "
                    "1000; horas_evitables = duración del episodio − 20 min; "
                    "episodios_mes = episodios × 30 / 14",
                    "calculo": [
                        f"{light.entity_id}: {light.power_w:g} W × {avoidable_h:g} h × "
                        f"({len(episodes)} × 30/14) / 1000 = {est:.3f} kWh"
                    ],
                    "resumen": f"{len(episodes)} veces en {WINDOW_DAYS} días",
                },
                est_kwh_month=round(est, 3),
                confidence="media",
                explanation=(
                    f"En {WINDOW_DAYS} días, {light.name} se quedó prendida {len(episodes)} veces "
                    "más de 20 minutos sin nadie cerca. Es un LED, así que el ahorro es pequeño, "
                    "pero suma."
                ),
            )
        )
    return out
