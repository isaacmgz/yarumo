#!/usr/bin/env bash
# Configura el panel de Energía de Home Assistant (docs/04-home-assistant.md, "Energía").
# Idempotente: reemplaza las preferencias de energía con las de la demo.
# Usa el WebSocket de HA desde dentro del contenedor (allí ya está aiohttp).
# Requiere HA_TOKEN y TARIFA_COP_KWH en .env. No imprime el token.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
. ./.env
set +a

podman exec -i -e HA_TOKEN -e TARIFA_COP_KWH homeassistant python - <<'PY'
import asyncio, json, os
import aiohttp

DEVICES = {
    "luz_sala": "Luz sala",
    "luz_cocina": "Luz cocina",
    "luz_habitacion_principal": "Luz habitación principal",
    "luz_habitacion_2": "Luz habitación 2",
    "luz_estudio": "Luz estudio",
    "tv_sala": "TV sala",
    "pc_estudio": "PC estudio",
    "ventilador_habitacion_principal": "Ventilador habitación principal",
    "plancha_ropa": "Plancha",
}
tarifa = float(os.environ.get("TARIFA_COP_KWH") or 0)

PREFS = {
    "type": "energy/save_prefs",
    "energy_sources": [{
        "type": "grid",
        "name": "Casa (medición simulada)",
        "stat_energy_from": "sensor.casa_energia_total",
        "stat_rate": "sensor.casa_potencia_total",
        # Sin tarifa definida no se inventa un costo.
        "number_energy_price": tarifa if tarifa > 0 else None,
        "cost_adjustment_day": 0,
    }],
    "device_consumption": [
        {"stat_consumption": f"sensor.{oid}_energia", "name": name}
        for oid, name in DEVICES.items()
    ],
}

async def main():
    async with aiohttp.ClientSession() as s, s.ws_connect("http://127.0.0.1:8123/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        if (await ws.receive_json())["type"] != "auth_ok":
            raise SystemExit("Token de HA rechazado")
        await ws.send_json({"id": 1, **PREFS})
        while (r := await ws.receive_json()).get("id") != 1:
            pass
        if not r["success"]:
            raise SystemExit(f"energy/save_prefs falló: {r['error']}")
        print("Panel de Energía configurado" + ("" if tarifa > 0 else " (sin tarifa: TARIFA_COP_KWH=0)"))

asyncio.run(asyncio.wait_for(main(), 20))
PY
