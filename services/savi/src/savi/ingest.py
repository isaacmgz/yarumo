"""Home Assistant ingestion: WebSocket state_changed subscription and a state cache.

docs/05-savi-ia.md §1. Power sensors only update the cache; everything else whitelisted is
stored as an event. On every (re)connection, GET /api/states refreshes the cache and stores a
reconciliation event for any tracked entity whose state changed while Savi was not listening.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx
from websockets.asyncio.client import connect as ws_connect

from .catalog import is_power_sensor, is_tracked
from .store import Event, Store

log = logging.getLogger("savi.ingest")

SUBSCRIBED_EVENTS = ("state_changed", "automation_triggered", "mobile_app_notification_action")
BACKOFF_START_S = 1.0
BACKOFF_MAX_S = 30.0


class AuthError(RuntimeError):
    pass


def _ts(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return default


def parse_state_changed(data: dict[str, Any], received_at: float) -> Event | None:
    """Turn a state_changed payload into an Event, or None if it is not worth storing.

    Attribute-only updates (same state) and non-whitelisted entities are dropped.
    Power sensors are returned too; the caller decides to cache them instead of storing.
    """
    entity_id = data.get("entity_id", "")
    if not is_tracked(entity_id):
        return None
    old, new = data.get("old_state") or {}, data.get("new_state") or {}
    old_state, new_state = old.get("state"), new.get("state")
    if old_state == new_state:
        return None
    return Event(
        ts=_ts(new.get("last_changed"), received_at),
        entity_id=entity_id,
        old_state=old_state,
        new_state=new_state,
        attributes={"friendly_name": (new.get("attributes") or {}).get("friendly_name")},
    )


class Ingest:
    def __init__(
        self,
        store: Store,
        ha_url: str,
        token: str | None,
        clock: Callable[[], float],
        connect: Callable[..., Any] = ws_connect,
        fetch_states: Callable[[], Awaitable[list[dict]]] | None = None,
    ) -> None:
        self.store = store
        self.ha_url = ha_url.rstrip("/")
        self.token = token
        self.clock = clock
        self._connect = connect
        self._fetch_states = fetch_states or self._http_states
        self.cache: dict[str, dict] = {}
        # Called for every subscribed event, after the cache is updated (H4 actions/savings).
        self.listener: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
        self.connected = False
        self.stored = 0
        self.last_event_at: float | None = None

    @property
    def ws_url(self) -> str:
        return self.ha_url.replace("https://", "wss://").replace("http://", "ws://") + (
            "/api/websocket"
        )

    async def _http_states(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{self.ha_url}/api/states", headers={"Authorization": f"Bearer {self.token}"}
            )
            r.raise_for_status()
            return r.json()

    def handle_state_changed(self, data: dict[str, Any]) -> Event | None:
        new = data.get("new_state")
        entity_id = data.get("entity_id", "")
        if new and is_tracked(entity_id):
            self.cache[entity_id] = new
        event = parse_state_changed(data, self.clock())
        if event is None or is_power_sensor(event.entity_id):
            return None
        self.store.add_events([event])
        self.stored += 1
        self.last_event_at = event.ts
        return event

    def load_states(self, states: list[dict]) -> int:
        """Fill the cache and reconcile states missed while disconnected. Returns events stored."""
        missed: list[Event] = []
        for s in states:
            entity_id = s.get("entity_id", "")
            if not is_tracked(entity_id):
                continue
            self.cache[entity_id] = s
            if is_power_sensor(entity_id):
                continue
            last = self.store.last_state(entity_id)
            if last != s.get("state"):
                missed.append(
                    Event(
                        ts=_ts(s.get("last_changed"), self.clock()),
                        entity_id=entity_id,
                        old_state=last,
                        new_state=s.get("state"),
                        attributes={"reconciled": True},
                    )
                )
        self.store.add_events(missed)
        return len(missed)

    async def run_once(self) -> None:
        async with self._connect(self.ws_url, max_size=None) as ws:
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_required":
                raise RuntimeError(f"unexpected greeting: {first.get('type')}")
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(await ws.recv())
            if auth.get("type") != "auth_ok":
                raise AuthError("Home Assistant rejected HA_TOKEN")
            for i, event_type in enumerate(SUBSCRIBED_EVENTS, start=1):
                await ws.send(
                    json.dumps({"id": i, "type": "subscribe_events", "event_type": event_type})
                )
            self.connected = True
            log.info("connected to %s", self.ws_url)
            try:
                reconciled = self.load_states(await self._fetch_states())
                log.info(
                    "state cache loaded (%d entities, %d reconciled)", len(self.cache), reconciled
                )
            except Exception:
                log.exception("could not load /api/states; continuing with events only")
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "result" and not msg.get("success", False):
                    log.warning("subscription failed: %s", msg.get("error"))
                if msg.get("type") != "event":
                    continue
                event = msg.get("event") or {}
                event_type, data = event.get("event_type", ""), event.get("data") or {}
                if event_type == "state_changed":
                    self.handle_state_changed(data)
                if self.listener is not None:
                    try:
                        await self.listener(event_type, data)
                    except Exception:
                        log.exception("listener failed on %s", event_type)

    async def run_forever(self) -> None:
        backoff = BACKOFF_START_S
        while True:
            try:
                await self.run_once()
                backoff = BACKOFF_START_S
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Home Assistant WebSocket lost (%s); retrying in %.0f s", exc, backoff)
            finally:
                self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
