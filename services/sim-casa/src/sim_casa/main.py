"""Entry point: wires settings, house, MQTT bridge, tick loop and the HTTP API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI

from .api import create_app
from .config import Settings
from .house import House, StateStore
from .mqtt_bridge import MqttBridge

log = logging.getLogger("sim_casa")


def build_app(settings: Settings) -> FastAPI:
    bridge = MqttBridge(
        settings.mqtt_host, settings.mqtt_port, settings.mqtt_user, settings.mqtt_password
    )
    tz = ZoneInfo(settings.tz)
    house = House(
        publisher=bridge,
        store=StateStore(settings.state_path),
        wall_clock=lambda: datetime.now(tz),
        motion_probability=settings.motion_probability,
        motion_check_s=settings.motion_check_s,
    )
    bridge.on_message_cb = house.handle_message
    bridge.on_connected_cb = house.publish_all

    async def tick_loop() -> None:
        while True:
            await asyncio.sleep(1)
            try:
                house.tick()
            except Exception:
                log.exception("tick failed")

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        bridge.start()
        task = asyncio.create_task(tick_loop())
        try:
            yield
        finally:
            task.cancel()
            house.tick()
            house.save()
            bridge.stop()

    return create_app(house, bridge.is_connected, lifespan=lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    app = build_app(settings)
    uvicorn.run(app, host=settings.sim_host, port=settings.sim_port, log_level="info")


if __name__ == "__main__":
    main()
