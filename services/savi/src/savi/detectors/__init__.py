"""Deterministic detectors D1–D3 and the R1 safety rule."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from ..store import Store
from . import consumo_nocturno, luz_sin_movimiento, olvido_al_salir, reglas_seguridad
from .base import Context, Proposal
from .timeline import build_timelines

DETECTORS = (olvido_al_salir, luz_sin_movimiento, consumo_nocturno, reglas_seguridad)


def run_all(store: Store, now: float, tz: ZoneInfo) -> list[Proposal]:
    ctx = Context(build_timelines(store.events(until=now)), now, tz)
    proposals: list[Proposal] = []
    for detector in DETECTORS:
        proposals.extend(detector.detect(ctx))
    return proposals
