"""D3 · consumo_nocturno: PC or TV ON between 00:00 and 05:00 with no motion for >= 30 min."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from ..catalog import DEVICES_BY_ID, MOTION_BY_ROOM
from .base import WINDOW_DAYS, Context, Proposal, per_month
from .timeline import median, subtract

NAME = "consumo_nocturno"
WATCHED = ("switch.pc_estudio", "switch.tv_sala")
QUIET_S = 30 * 60
MIN_NIGHTS = 4
NIGHT_START = time(0, 0)
NIGHT_END = time(5, 0)
ACTION_FROM = time(1, 0)  # the automation acts from 01:00


def _nights(ctx: Context) -> list[datetime]:
    """Local midnights whose 00:00–05:00 window lies fully inside the analysis window."""
    first = ctx.local(ctx.window_start).date()
    last = ctx.local(ctx.now).date()
    out = []
    d = first
    while d <= last:
        start = datetime.combine(d, NIGHT_START, ctx.tz)
        end = datetime.combine(d, NIGHT_END, ctx.tz)
        if start.timestamp() >= ctx.window_start and end.timestamp() <= ctx.now:
            out.append(start)
        d += timedelta(days=1)
    return out


def detect(ctx: Context) -> list[Proposal]:
    out: list[Proposal] = []
    nights = _nights(ctx)
    for entity_id in WATCHED:
        device = DEVICES_BY_ID[entity_id]
        tl = ctx.timelines.get(entity_id)
        motion_tl = ctx.timelines.get(MOTION_BY_ROOM[device.room])
        if tl is None or motion_tl is None:
            continue
        hits: list[tuple[datetime, float]] = []  # (night, avoidable hours)
        synthetic = False
        for night in nights:
            ns = night.timestamp()
            ne = datetime.combine(night.date(), NIGHT_END, ctx.tz).timestamp()
            act = datetime.combine(night.date(), ACTION_FROM, ctx.tz).timestamp()
            quiet = subtract(tl.on_intervals(ns, ne), motion_tl.on_intervals(ns, ne))
            runs = [(a, b) for a, b in quiet if b - a >= QUIET_S]
            if not runs:
                continue
            # From 01:00, after 30 min without motion the automation would turn it off.
            avoidable = max(max(0.0, b - max(act, a + QUIET_S)) for a, b in runs) / 3600
            hits.append((night, avoidable))
            synthetic |= tl.synthetic_in(ns, ne)
        if len(hits) < MIN_NIGHTS:
            continue
        avoidable_h = round(median([h for _, h in hits]), 3)
        nights_month = per_month(len(hits))
        est = device.power_w * avoidable_h * nights_month / 1000
        out.append(
            Proposal(
                detector=NAME,
                title=f"Apagar {device.name} de madrugada",
                entities=[entity_id],
                evidence={
                    "ventana_dias": WINDOW_DAYS,
                    "noches": len(hits),
                    "noches_analizadas": len(nights),
                    "potencia_w": device.power_w,
                    "mediana_horas_evitables": avoidable_h,
                    "noches_mes": round(nights_month, 3),
                    "fechas_ejemplo": [n.date().isoformat() for n, _ in hits[-3:]],
                    "datos_simulados": synthetic,
                    "formula": "kWh_mes = potencia × mediana_horas_evitables × noches_mes / 1000;"
                    " horas_evitables = desde max(01:00, 30 min sin movimiento) hasta el fin del"
                    " encendido, sin pasar de las 05:00; noches_mes = noches × 30 / 14",
                    "calculo": [
                        f"{entity_id}: {device.power_w:g} W × {avoidable_h:g} h × "
                        f"({len(hits)} × 30/14) / 1000 = {est:.3f} kWh"
                    ],
                    "resumen": f"{len(hits)} de {len(nights)} noches",
                },
                est_kwh_month=round(est, 3),
                confidence="media",
                explanation=(
                    f"En {len(hits)} de {len(nights)} noches {device.name} quedó prendido de "
                    "madrugada sin nadie cerca. Desde la 1:00 puedo apagarlo si no hay movimiento "
                    "en 30 minutos."
                ),
            )
        )
    return out
