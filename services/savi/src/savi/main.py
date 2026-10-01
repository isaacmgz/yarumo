"""Entry point: wires settings, store, HA ingestion, the hourly detector loop and the API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from fastapi import FastAPI

from .api import Savi, create_app
from .config import Settings
from .ingest import Ingest
from .store import Store
from .suggestions import Tariff

log = logging.getLogger("savi")


def build_app(settings: Settings) -> FastAPI:
    store = Store(settings.db_path)
    savi = Savi(
        store,
        ZoneInfo(settings.tz),
        Tariff(settings.tariff_cop_kwh, settings.tariff_verified),
        time.time,
        settings.demo_mode,
    )
    ingest = Ingest(store, settings.ha_url, settings.ha_token, time.time)

    async def health_probe() -> dict:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                r = await client.get(f"{settings.ollama_url}/api/tags")
            ollama = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except httpx.HTTPError:
            ollama = "sin respuesta"
        return {
            "ha_ws": "connected" if ingest.connected else "disconnected",
            "mqtt": "pendiente (H4)",
            "ollama": ollama,
            "eventos": store.count_events(),
            "eventos_ingeridos": ingest.stored,
            "ultimo_evento": savi._iso(ingest.last_event_at),
            "detectores": savi.last_run,
            "tarifa": {
                "cop_kwh": settings.tariff_cop_kwh,
                "verificada": settings.tariff_verified,
            },
        }

    async def detector_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(savi.run_detectors)
            except Exception:
                log.exception("detector run failed")
            await asyncio.sleep(settings.detectors_interval_s)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(detector_loop())]
        if settings.ha_token:
            tasks.append(asyncio.create_task(ingest.run_forever()))
        else:
            log.warning("HA_TOKEN not set; ingestion disabled")
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            store.close()

    return create_app(savi, health_probe, lifespan=lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(build_app(settings), host=settings.savi_host, port=settings.savi_port)


if __name__ == "__main__":
    main()
