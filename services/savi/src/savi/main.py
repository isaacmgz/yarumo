"""Entry point: wires settings, store, HA ingestion and actions, MQTT sensors, loops and the API."""

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
from .ha_client import HaClient
from .ingest import Ingest
from .mqtt_out import MqttOut
from .store import Store
from .suggestions import Tariff

log = logging.getLogger("savi")


def build_app(settings: Settings) -> FastAPI:
    store = Store(settings.db_path)
    ingest = Ingest(store, settings.ha_url, settings.ha_token, time.time)
    ha = (
        HaClient(settings.ha_url, settings.ha_token, settings.automations_path)
        if settings.ha_token
        else None
    )
    mqtt_box: dict[str, MqttOut] = {}

    def publish_sensors() -> None:
        if "out" in mqtt_box:
            mqtt_box["out"].publish_states()

    savi = Savi(
        store,
        ZoneInfo(settings.tz),
        Tariff(settings.tariff_cop_kwh, settings.tariff_verified),
        time.time,
        settings.demo_mode,
        ha=ha,
        cache=ingest.cache,
        on_change=publish_sensors,
    )
    ingest.listener = savi.handle_ha_event
    mqtt_box["out"] = MqttOut(
        settings.mqtt_host,
        settings.mqtt_port,
        settings.mqtt_user,
        settings.mqtt_password,
        savi.sensor_values,
    )

    async def health_probe() -> dict:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                r = await client.get(f"{settings.ollama_url}/api/tags")
            ollama = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except httpx.HTTPError:
            ollama = "sin respuesta"
        return {
            "ha_ws": "connected" if ingest.connected else "disconnected",
            "mqtt": "connected" if mqtt_box["out"].is_connected() else "disconnected",
            "ollama": ollama,
            "eventos": store.count_events(),
            "eventos_ingeridos": ingest.stored,
            "ultimo_evento": savi._iso(ingest.last_event_at),
            "detectores": savi.last_run,
            "ahorros_en_curso": len(store.savings("en_curso")),
            "tarifa": {
                "cop_kwh": settings.tariff_cop_kwh,
                "verificada": settings.tariff_verified,
            },
        }

    async def detector_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(savi.run_detectors)
                await savi.notify_new()
                publish_sensors()
            except Exception:
                log.exception("detector run failed")
            await asyncio.sleep(settings.detectors_interval_s)

    async def tick_loop() -> None:
        # Closes records at the 8 h cap / 06:00 and refreshes the live counters every minute.
        while True:
            try:
                savi.tick()
                publish_sensors()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(settings.tick_s)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        mqtt_box["out"].start()
        tasks = [asyncio.create_task(detector_loop()), asyncio.create_task(tick_loop())]
        if settings.ha_token:
            tasks.append(asyncio.create_task(ingest.run_forever()))
        else:
            log.warning("HA_TOKEN not set; ingestion and actions disabled")
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            mqtt_box["out"].stop()
            store.close()

    return create_app(savi, health_probe, lifespan=lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(build_app(settings), host=settings.savi_host, port=settings.savi_port)


if __name__ == "__main__":
    main()
