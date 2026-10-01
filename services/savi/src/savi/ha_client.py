"""Home Assistant REST: services, states and automation creation (docs/05-savi-ia.md §4).

`POST /api/config/automation/config/<id>` is what HA's automation editor uses; it is not in
the public REST docs, so it lives here, isolated. Plan B when it fails: write the automation
into a shared `automations.yaml` and call `automation.reload`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import yaml

log = logging.getLogger("savi.ha")

VERIFY_ATTEMPTS = 10
VERIFY_DELAY_S = 0.5


class HaError(RuntimeError):
    pass


class HaClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        automations_path: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.automations_path = Path(automations_path) if automations_path else None
        self._transport = transport
        self._sleep = sleep

    async def _request(self, method: str, path: str, json: Any = None) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=10,
            transport=self._transport,
        ) as client:
            r = await client.request(method, path, json=json)
        r.raise_for_status()
        return r

    async def call_service(self, domain: str, service: str, data: dict | None = None) -> None:
        try:
            await self._request("POST", f"/api/services/{domain}/{service}", json=data or {})
        except httpx.HTTPError as exc:
            raise HaError(f"{domain}.{service} failed: {exc}") from exc

    async def states(self) -> list[dict]:
        try:
            return (await self._request("GET", "/api/states")).json()
        except httpx.HTTPError as exc:
            raise HaError(f"GET /api/states failed: {exc}") from exc

    # ---- automations --------------------------------------------------

    async def create_automation(self, automation_id: str, config: dict) -> str:
        """Create or replace the automation. Returns the method used: "config_api" or "yaml"."""
        body = {"id": automation_id, **config}
        try:
            await self._request("POST", f"/api/config/automation/config/{automation_id}", body)
            method = "config_api"
        except httpx.HTTPError as exc:
            if self.automations_path is None:
                raise HaError(f"config API failed and no plan B path is set: {exc}") from exc
            log.warning("config API failed (%s); plan B: writing %s", exc, self.automations_path)
            self._write_yaml(body)
            method = "yaml"
        await self.call_service("automation", "reload")
        return method

    def _write_yaml(self, automation: dict) -> None:
        path = self.automations_path
        assert path is not None
        current = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
        items = [a for a in (current or []) if a.get("id") != automation["id"]]
        items.append(automation)
        # Write in place: the file may be a single-file bind mount, where rename fails.
        path.write_text(
            yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    async def delete_automation(self, automation_id: str) -> None:
        try:
            await self._request("DELETE", f"/api/config/automation/config/{automation_id}")
        except httpx.HTTPError as exc:
            raise HaError(f"delete {automation_id} failed: {exc}") from exc

    async def find_automation(self, automation_id: str) -> str | None:
        """HA derives the entity_id from the alias, so match on the `id` attribute instead."""
        for s in await self.states():
            entity_id = s.get("entity_id", "")
            if (
                entity_id.startswith("automation.")
                and (s.get("attributes") or {}).get("id") == automation_id
            ):
                return entity_id
        return None

    async def wait_for_automation(self, automation_id: str) -> str | None:
        for _ in range(VERIFY_ATTEMPTS):
            entity_id = await self.find_automation(automation_id)
            if entity_id:
                return entity_id
            await self._sleep(VERIFY_DELAY_S)
        return None
