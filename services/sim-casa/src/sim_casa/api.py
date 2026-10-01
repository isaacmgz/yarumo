"""Scenario HTTP API (docs/03-contrato-mqtt.md, port SIM_PORT)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .house import House, UnknownDevice, UnknownScenario


class DeviceCommand(BaseModel):
    estado: Literal["ON", "OFF"]


def create_app(
    house: House,
    mqtt_connected: Callable[[], bool],
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]] | None = None,
) -> FastAPI:
    app = FastAPI(title="sim-casa", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "mqtt": "connected" if mqtt_connected() else "disconnected"}

    @app.get("/dispositivos")
    def list_devices() -> list[dict]:
        return house.snapshot()

    @app.post("/dispositivos/{object_id}")
    def set_device(object_id: str, command: DeviceCommand) -> dict:
        try:
            return house.set_device(object_id, command.estado == "ON")
        except UnknownDevice as exc:
            raise HTTPException(404, f"No conozco el dispositivo '{object_id}'.") from exc

    @app.post("/escenarios/{name}")
    def scenario(name: str) -> dict:
        try:
            devices = house.apply_scenario(name)
        except UnknownScenario as exc:
            raise HTTPException(404, f"No conozco el escenario '{name}'.") from exc
        return {"escenario": name, "dispositivos": devices}

    return app
