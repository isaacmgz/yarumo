"""HA WebSocket ingestion with a fake socket (no live Home Assistant)."""

from __future__ import annotations

import asyncio
import json

import pytest

from savi.ingest import AuthError, Ingest, parse_state_changed

T0 = "2026-09-30T20:00:00.000000+00:00"


def change(entity_id, old, new, last_changed=T0, attrs=None):
    return {
        "entity_id": entity_id,
        "old_state": None if old is None else {"state": old},
        "new_state": {"state": new, "last_changed": last_changed, "attributes": attrs or {}},
    }


def event_msg(data):
    return json.dumps({"type": "event", "event": {"event_type": "state_changed", "data": data}})


class FakeWS:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, msg):
        self.sent.append(json.loads(msg))

    async def recv(self):
        return self.incoming.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return self.incoming.pop(0)


def make_ingest(store, ws, states=()):
    async def fetch():
        return list(states)

    return Ingest(
        store,
        "http://ha:8123",
        "tok",
        lambda: 1000.0,
        connect=lambda url, **kw: ws,
        fetch_states=fetch,
    )


def test_parse_state_changed():
    e = parse_state_changed(change("switch.tv_sala", "off", "on"), 0)
    assert (e.entity_id, e.old_state, e.new_state) == ("switch.tv_sala", "off", "on")
    assert e.ts == pytest.approx(1790798400.0) and e.synthetic is False
    assert parse_state_changed(change("switch.tv_sala", "on", "on"), 0) is None  # attrs only
    assert parse_state_changed(change("sun.sun", "a", "b"), 0) is None  # not whitelisted
    assert parse_state_changed(change("binary_sensor.casa_ocupada", "on", "off"), 0)


def test_run_once_authenticates_subscribes_and_stores(store):
    ws = FakeWS(
        [
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
            event_msg(change("switch.tv_sala", "off", "on")),
            event_msg(change("sensor.tv_sala_potencia", "0.0", "90.0")),
            event_msg(change("binary_sensor.movimiento_sala", "off", "on")),
            event_msg(change("light.nevera", "off", "on")),
        ]
    )
    ingest = make_ingest(
        store,
        ws,
        states=[{"entity_id": "binary_sensor.casa_ocupada", "state": "on", "last_changed": T0}],
    )
    asyncio.run(ingest.run_once())

    assert ws.sent[0] == {"type": "auth", "access_token": "tok"}
    assert [m["event_type"] for m in ws.sent[1:]][0] == "state_changed"
    stored = [(e.entity_id, e.new_state) for e in store.events()]
    assert stored == [
        ("binary_sensor.casa_ocupada", "on"),  # reconciled from /api/states
        ("switch.tv_sala", "on"),
        ("binary_sensor.movimiento_sala", "on"),
    ]
    assert ingest.cache["sensor.tv_sala_potencia"]["state"] == "90.0"  # power: cache only
    assert ingest.stored == 2


def test_reconnect_does_not_duplicate_unchanged_states(store):
    states = [{"entity_id": "switch.tv_sala", "state": "off", "last_changed": T0}]
    ingest = make_ingest(store, FakeWS([]), states)
    assert ingest.load_states(states) == 1
    assert ingest.load_states(states) == 0


def test_bad_token_raises(store):
    ws = FakeWS([json.dumps({"type": "auth_required"}), json.dumps({"type": "auth_invalid"})])
    with pytest.raises(AuthError):
        asyncio.run(make_ingest(store, ws).run_once())
    assert make_ingest(store, ws).ws_url == "ws://ha:8123/api/websocket"
