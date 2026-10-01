"""HA REST client with httpx.MockTransport, plus an opt-in integration test against real HA."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
import yaml

from savi.ha_client import HaClient, HaError


async def _no_sleep(_):
    return None


def make(handler, path=None):
    return HaClient(
        "http://ha:8123", "tok", path, transport=httpx.MockTransport(handler), sleep=_no_sleep
    )


def test_create_uses_config_api_then_reloads():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content or b"null")))
        assert req.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"result": "ok"})

    method = asyncio.run(make(handler).create_automation("savi_2", {"alias": "Savi · X"}))
    assert method == "config_api"
    assert calls[0] == (
        "POST",
        "/api/config/automation/config/savi_2",
        {"id": "savi_2", "alias": "Savi · X"},
    )
    assert calls[1][:2] == ("POST", "/api/services/automation/reload")


def test_plan_b_writes_automations_yaml_when_config_api_fails(tmp_path):
    path = tmp_path / "automations.yaml"
    path.write_text("- id: otra\n  alias: Otra\n", encoding="utf-8")
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        if "/config/automation/" in req.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json=[])

    client = make(handler, str(path))
    assert asyncio.run(client.create_automation("savi_2", {"alias": "Savi · X"})) == "yaml"
    asyncio.run(client.create_automation("savi_2", {"alias": "Savi · Y"}))  # replaces, no dup
    items = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [i["id"] for i in items] == ["otra", "savi_2"]
    assert items[1]["alias"] == "Savi · Y"
    assert seen[-1] == "/api/services/automation/reload"


def test_config_api_failure_without_plan_b_raises():
    with pytest.raises(HaError):
        asyncio.run(make(lambda req: httpx.Response(500)).create_automation("savi_1", {}))


def test_find_automation_matches_the_id_attribute_not_the_entity_id():
    states = [
        {"entity_id": "automation.savi_2", "attributes": {"id": "otra"}},
        {"entity_id": "automation.savi_apagar_lo_que_queda", "attributes": {"id": "savi_2"}},
    ]
    client = make(lambda req: httpx.Response(200, json=states))
    found = asyncio.run(client.wait_for_automation("savi_2"))
    assert found == "automation.savi_apagar_lo_que_queda"
    assert asyncio.run(client.wait_for_automation("savi_9")) is None


@pytest.mark.skipif(
    not (os.environ.get("SAVI_IT") and os.environ.get("HA_TOKEN")),
    reason="integration: set SAVI_IT=1, HA_URL and HA_TOKEN to run against the real HA",
)
def test_integration_create_verify_delete_savi_test():
    client = HaClient(os.environ.get("HA_URL", "http://127.0.0.1:8123"), os.environ["HA_TOKEN"])
    config = {
        "alias": "Savi · prueba de integración",
        "description": "Creada y borrada por el test de integración de Savi.",
        "triggers": [{"trigger": "event", "event_type": "savi_test_never_fired"}],
        "actions": [],
    }

    async def run():
        await client.create_automation("savi_test", config)
        entity_id = await client.wait_for_automation("savi_test")
        await client.delete_automation("savi_test")
        return entity_id

    assert asyncio.run(run()) is not None
