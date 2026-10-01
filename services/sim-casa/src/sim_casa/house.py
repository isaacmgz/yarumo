"""Simulated house: device state, power, energy integration, sensors and scenarios.

All time-dependent behavior is driven by `tick()` with an injectable clock, so tests can
run hours of simulation instantly and without a broker.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .catalog import (
    BASE,
    DEVICES,
    DEVICES_BY_ID,
    DOOR,
    MOTION_BY_ROOM,
    OCCUPANCY_TOPIC,
    TEMPERATURE,
    Device,
)

log = logging.getLogger(__name__)

PUBLISH_INTERVAL_S = 30.0
TEMPERATURE_INTERVAL_S = 60.0
MOTION_PULSE_S = 30.0
DOOR_PULSE_S = 5.0

# Scenario name -> set of devices that must be ON. `exclusive` scenarios turn the rest OFF.
SCENARIOS: dict[str, tuple[frozenset[str], bool]] = {
    "manana_laboral": (
        frozenset({"luz_cocina", "luz_habitacion_principal", "tv_sala", "pc_estudio"}),
        True,
    ),
    "olvido_salida": (frozenset({"tv_sala", "pc_estudio", "luz_estudio"}), True),
    "plancha_olvidada": (frozenset({"plancha_ropa"}), False),
    "noche": (frozenset({"luz_habitacion_principal", "ventilador_habitacion_principal"}), True),
    "reset": (frozenset(), True),
}


class Publisher(Protocol):
    def publish(self, topic: str, payload: str, retain: bool = True) -> None: ...


class UnknownDevice(KeyError):
    pass


class UnknownScenario(KeyError):
    pass


class StateStore:
    """Persists energy accumulators and on/off state as JSON (atomic replace)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            log.exception("Could not read state file %s; starting from zero", self.path)
            return {}

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)


def medellin_temperature(now: datetime) -> float:
    """Smooth daily curve: ~18 °C at 05:00, ~27 °C at 14:00 (no noise)."""
    t_min, t_max, h_min, h_max = 18.0, 27.0, 5.0, 14.0
    mid, amp = (t_min + t_max) / 2, (t_max - t_min) / 2
    hour = now.hour + now.minute / 60 + now.second / 3600
    if h_min <= hour < h_max:
        frac = (hour - h_min) / (h_max - h_min)
        return mid - amp * math.cos(math.pi * frac)
    frac = ((hour - h_max) % 24) / (24 - (h_max - h_min))
    return mid + amp * math.cos(math.pi * frac)


def fmt_power(watts: float) -> str:
    return f"{watts:.1f}"


def fmt_energy(kwh: float) -> str:
    return f"{kwh:.4f}"


class House:
    def __init__(
        self,
        publisher: Publisher,
        store: StateStore | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        motion_probability: float = 0.5,
        motion_check_s: float = 15.0,
    ):
        self._pub = publisher
        self._store = store
        self._clock = clock
        self._wall = wall_clock or (lambda: datetime.now())
        self._rng = rng or random.Random()
        self._motion_probability = motion_probability
        self._motion_check_s = motion_check_s
        self._lock = threading.RLock()

        self.on: dict[str, bool] = {d.object_id: False for d in DEVICES}
        self.energy_kwh: dict[str, float] = {d.object_id: 0.0 for d in DEVICES}
        self.occupied: bool | None = None
        self.motion_until: dict[str, float] = {}
        self.door_until: float | None = None
        self.temperature: float | None = None

        if store is not None:
            saved = store.load()
            for oid, kwh in saved.get("energia_kwh", {}).items():
                if oid in self.energy_kwh:
                    self.energy_kwh[oid] = float(kwh)
            for oid, state in saved.get("encendido", {}).items():
                if oid in self.on:
                    self.on[oid] = bool(state)

        now = self._clock()
        self._last_integration = now
        self._last_periodic = now
        self._last_temperature: float | None = None
        self._last_motion_check = now

    # ---- power & energy -------------------------------------------------

    @staticmethod
    def _power(device: Device, on: bool) -> float:
        return device.power_on_w if on else device.standby_w

    def power_w(self, object_id: str) -> float:
        return self._power(DEVICES_BY_ID[object_id], self.on[object_id])

    def _integrate(self, now: float) -> None:
        dt = now - self._last_integration
        if dt > 0:
            for d in DEVICES:
                self.energy_kwh[d.object_id] += self.power_w(d.object_id) * dt / 3_600_000
        self._last_integration = now

    # ---- publishing -----------------------------------------------------

    def _publish_device(self, d: Device, energy: bool = False) -> None:
        oid = d.object_id
        self._pub.publish(d.topic("estado"), "ON" if self.on[oid] else "OFF")
        self._pub.publish(d.topic("potencia"), fmt_power(self.power_w(oid)))
        if energy:
            self._pub.publish(d.topic("energia"), fmt_energy(self.energy_kwh[oid]))

    def publish_all(self) -> None:
        """Publish every state (used after (re)connecting to the broker)."""
        with self._lock:
            now = self._clock()
            self._integrate(now)
            for d in DEVICES:
                self._publish_device(d, energy=True)
            for room, sensor in MOTION_BY_ROOM.items():
                active = self.motion_until.get(room, 0) > now
                self._pub.publish(sensor.state_topic, "ON" if active else "OFF")
            door_open = self.door_until is not None and self.door_until > now
            self._pub.publish(DOOR.state_topic, "ON" if door_open else "OFF")
            self._publish_temperature(now)

    def _publish_temperature(self, now: float) -> None:
        noise = self._rng.uniform(-0.3, 0.3)
        self.temperature = round(medellin_temperature(self._wall()) + noise, 1)
        self._pub.publish(TEMPERATURE.state_topic, f"{self.temperature:.1f}")
        self._last_temperature = now

    # ---- commands -------------------------------------------------------

    def set_device(self, object_id: str, on: bool) -> dict:
        device = DEVICES_BY_ID.get(object_id)
        if device is None:
            raise UnknownDevice(object_id)
        with self._lock:
            self._integrate(self._clock())
            self.on[object_id] = on
            self._publish_device(device, energy=True)
            self.save()
            return self.device_view(device)

    def apply_scenario(self, name: str) -> list[dict]:
        if name not in SCENARIOS:
            raise UnknownScenario(name)
        turn_on, exclusive = SCENARIOS[name]
        with self._lock:
            for d in DEVICES:
                if d.object_id in turn_on:
                    self.set_device(d.object_id, True)
                elif exclusive:
                    self.set_device(d.object_id, False)
            return self.snapshot()

    def set_occupied(self, occupied: bool) -> None:
        with self._lock:
            now = self._clock()
            previous = self.occupied
            self.occupied = occupied
            if previous is not None and previous != occupied:
                self.door_until = now + DOOR_PULSE_S
                self._pub.publish(DOOR.state_topic, "ON")
            if not occupied:
                for room in list(self.motion_until):
                    del self.motion_until[room]
                    self._pub.publish(MOTION_BY_ROOM[room].state_topic, "OFF")

    def handle_message(self, topic: str, payload: bytes) -> None:
        text = payload.decode("utf-8", errors="replace").strip()
        if topic == OCCUPANCY_TOPIC:
            value = text.lower()
            if value in {"true", "false"}:
                self.set_occupied(value == "true")
            else:
                log.warning("Ignoring occupancy payload %r", text)
            return
        prefix, suffix = f"{BASE}/", "/set"
        if topic.startswith(prefix) and topic.endswith(suffix):
            object_id = topic[len(prefix) : -len(suffix)]
            command = text.upper()
            if object_id not in DEVICES_BY_ID or command not in {"ON", "OFF"}:
                log.warning("Ignoring command %r on %s", text, topic)
                return
            self.set_device(object_id, command == "ON")

    # ---- time -----------------------------------------------------------

    def tick(self) -> None:
        """Advance the simulation; called about once per second."""
        with self._lock:
            now = self._clock()
            self._integrate(now)

            for room in [r for r, until in self.motion_until.items() if until <= now]:
                del self.motion_until[room]
                self._pub.publish(MOTION_BY_ROOM[room].state_topic, "OFF")
            if self.door_until is not None and self.door_until <= now:
                self.door_until = None
                self._pub.publish(DOOR.state_topic, "OFF")

            if now - self._last_motion_check >= self._motion_check_s:
                self._last_motion_check = now
                self._maybe_motion(now)

            if now - self._last_periodic >= PUBLISH_INTERVAL_S:
                self._last_periodic = now
                for d in DEVICES:
                    self._pub.publish(d.topic("potencia"), fmt_power(self.power_w(d.object_id)))
                    self._pub.publish(d.topic("energia"), fmt_energy(self.energy_kwh[d.object_id]))
                self.save()

            if self._last_temperature is None or now - self._last_temperature >= (
                TEMPERATURE_INTERVAL_S
            ):
                self._publish_temperature(now)

    def _maybe_motion(self, now: float) -> None:
        if not self.occupied:
            return
        active_rooms = {DEVICES_BY_ID[oid].room for oid, on in self.on.items() if on}
        for room in sorted(active_rooms):
            if room in self.motion_until or room not in MOTION_BY_ROOM:
                continue
            if self._rng.random() < self._motion_probability:
                self.motion_until[room] = now + MOTION_PULSE_S
                self._pub.publish(MOTION_BY_ROOM[room].state_topic, "ON")

    # ---- views & persistence --------------------------------------------

    def device_view(self, d: Device) -> dict:
        return {
            "id": d.object_id,
            "tipo": d.component,
            "cuarto": d.room,
            "estado": "ON" if self.on[d.object_id] else "OFF",
            "potencia_w": self.power_w(d.object_id),
            "energia_kwh": round(self.energy_kwh[d.object_id], 4),
        }

    def snapshot(self) -> list[dict]:
        with self._lock:
            self._integrate(self._clock())
            return [self.device_view(d) for d in DEVICES]

    def save(self) -> None:
        if self._store is None:
            return
        with self._lock:
            try:
                self._store.save(
                    {
                        "energia_kwh": dict(self.energy_kwh),
                        "encendido": dict(self.on),
                        "guardado": datetime.now().isoformat(timespec="seconds"),
                    }
                )
            except OSError:
                log.exception("Could not persist state to %s", self._store.path)
