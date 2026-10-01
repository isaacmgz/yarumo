"""Runtime configuration, read only from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    ha_url: str
    ha_token: str | None
    ollama_url: str
    tz: str
    tariff_cop_kwh: float
    tariff_verified: bool
    savi_host: str
    savi_port: int
    demo_mode: bool
    db_path: str
    detectors_interval_s: float
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_user: str | None = None
    mqtt_password: str | None = None
    automations_path: str | None = None  # plan B: HA's automations.yaml on a shared volume
    tick_s: float = 60.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        return cls(
            ha_url=e.get("HA_URL", "http://127.0.0.1:8123").rstrip("/"),
            ha_token=e.get("HA_TOKEN") or None,
            ollama_url=e.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            tz=e.get("TZ", "America/Bogota"),
            tariff_cop_kwh=_float(e.get("TARIFA_COP_KWH"), 0.0),
            tariff_verified=_bool(e.get("TARIFA_VERIFICADA"), False),
            savi_host=e.get("SAVI_HOST", "0.0.0.0"),
            savi_port=int(e.get("SAVI_PORT", "8088")),
            demo_mode=_bool(e.get("DEMO_MODE"), True),
            db_path=e.get("SAVI_DB_PATH", "/data/savi.db"),
            detectors_interval_s=_float(e.get("SAVI_DETECTORS_INTERVAL_S"), 3600.0),
            mqtt_host=e.get("MQTT_HOST", "127.0.0.1"),
            mqtt_port=int(e.get("MQTT_PORT", "1883")),
            mqtt_user=e.get("MQTT_USER") or None,
            mqtt_password=e.get("MQTT_PASSWORD") or None,
            automations_path=e.get("SAVI_AUTOMATIONS_PATH") or None,
            tick_s=_float(e.get("SAVI_TICK_S"), 60.0),
        )
