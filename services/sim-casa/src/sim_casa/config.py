"""Runtime configuration, read only from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_password: str | None
    sim_host: str
    sim_port: int
    tz: str
    demo_mode: bool
    state_path: str
    motion_probability: float
    motion_check_s: float

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        return cls(
            mqtt_host=e.get("MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(e.get("MQTT_PORT", "1883")),
            mqtt_user=e.get("MQTT_USER") or None,
            mqtt_password=e.get("MQTT_PASSWORD") or None,
            sim_host=e.get("SIM_HOST", "0.0.0.0"),
            sim_port=int(e.get("SIM_PORT", "8090")),
            tz=e.get("TZ", "America/Bogota"),
            demo_mode=_bool(e.get("DEMO_MODE"), True),
            state_path=e.get("SIM_STATE_PATH", "/data/state.json"),
            motion_probability=float(e.get("SIM_MOTION_PROBABILITY", "0.5")),
            motion_check_s=float(e.get("SIM_MOTION_CHECK_S", "15")),
        )
