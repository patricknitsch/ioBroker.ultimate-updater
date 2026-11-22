"""Fixtures: a small fake of the Ultimate Updater integration API v1."""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any
from urllib.parse import unquote

import pytest
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.ultimate_updater.const import CONF_VALIDATE_CERT, DOMAIN

HOST = "192.0.2.10"
BASE = f"https://{HOST}:8765/api/v1"
ENTRY_DATA = {CONF_HOST: HOST, CONF_PORT: 8765, CONF_API_TOKEN: "tok-full", CONF_VALIDATE_CERT: False}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeUu:
    """Behaviour as in web-ui/server.py (see test/mockUuServer.js of the ioBroker adapter)."""

    def __init__(self) -> None:
        self.targets: list[dict[str, Any]] = [
            {"id": "lxc:101", "name": "web", "type": "lxc", "node": "pve", "reachable": True,
             "security_updates": 2, "normal_updates": 5, "reboot_required": False, "check_status": "updates_available"},
            {"id": "host:pve", "name": "pve", "type": "host", "node": "pve", "reachable": True,
             "security_updates": 0, "normal_updates": 1, "reboot_required": True, "check_status": "updates_available"},
            {"id": "lxc:103", "name": "db", "type": "lxc", "node": "pve", "reachable": True,
             "security_updates": 1, "normal_updates": 0, "reboot_required": False, "check_status": "updates_available"},
            {"id": "vm:200", "name": "win", "type": "vm", "node": "pve", "reachable": True,
             "security_updates": 0, "normal_updates": 0, "reboot_required": False, "check_status": "ok"},
        ]  # fmt: skip
        self.jobs: list[dict[str, Any]] = [{"unit": "uu-0", "target": "lxc:102", "state": "failed", "exit_code": 1}]
        self.calls: list[tuple[str, str, Any]] = []
        self.status: HTTPStatus | None = None  # forced HTTP status for every request
        self.counter = 0
        self.auto_complete = False  # jobs finish on the next /jobs read

    def _response(self, method: str, url: Any, status: int, data: Any) -> AiohttpClientMockResponse:
        return AiohttpClientMockResponse(method, url, status=status, json=data)

    async def handle(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        path = unquote(url.raw_path).removeprefix("/api/v1/")
        self.calls.append((method.upper(), path, data))
        if self.status is not None:
            code = {401: "AUTH_REQUIRED", 403: "PERMISSION_DENIED"}.get(int(self.status), "ERROR")
            return self._response(method, url, self.status, {"error": {"code": code, "message": "nope"}})
        parts = path.split("/")
        if method.upper() == "GET":
            if path == "status":
                return self._response(method, url, 200, {
                    "api_version": 1, "schema_version": 1, "generated_at": "2026-10-17T08:00:00Z",
                    "targets": self.targets,
                })  # fmt: skip
            if path == "jobs":
                jobs = [dict(j) for j in self.jobs]
                if self.auto_complete:
                    for j in self.jobs:
                        if j["state"] == "running":
                            j["state"] = "completed"
                return self._response(method, url, 200, {"jobs": jobs})
            if path == "updater-version":
                return self._response(
                    method, url, 200, {"installed": "5.2.0", "available": "5.2.1", "update_available": True}
                )
            if parts[0] == "jobs" and parts[-1] == "log":
                return self._response(method, url, 200, {"unit": parts[1], "log": "E: apt failed"})
            return self._response(method, url, 404, {"error": {"code": "NOT_FOUND"}})
        # POST
        route = parts[0]
        if route in ("update", "update-node", "reboot") and data != {"confirm": True}:
            return self._response(method, url, 422, {"error": {"code": "CONFIRMATION_REQUIRED"}})
        if route == "check" and parts[1].startswith("host:"):
            return self._response(method, url, 422, {"error": {"code": "USE_NODE_ACTION"}})
        if route == "jobs" and parts[-1] == "cancel":
            for j in self.jobs:
                if j["unit"] == parts[1]:
                    j["state"] = "interrupted"
            return self._response(method, url, 202, {"ok": True})
        self.counter += 1
        unit = f"uu-{self.counter}"
        target = parts[1] if len(parts) > 1 else "all"
        jtype = route
        self.jobs.append({"unit": unit, "target": target, "state": "running", "type": jtype,
                          "started_at": f"2026-10-17T08:00:{self.counter:02d}Z"})  # fmt: skip
        return self._response(method, url, 202, {"job": unit, "message": "started"})

    def posts(self) -> list[tuple[str, Any]]:
        return [(p, d) for m, p, d in self.calls if m == "POST"]

    def finish_all(self, state: str = "completed") -> None:
        for j in self.jobs:
            if j["state"] == "running":
                j["state"] = state


@pytest.fixture
def fake_uu(aioclient_mock: AiohttpClientMocker) -> FakeUu:
    fake = FakeUu()
    pattern = re.compile(r"/api/v1/")
    aioclient_mock.get(pattern, side_effect=fake.handle)
    aioclient_mock.post(pattern, side_effect=fake.handle)
    return fake


@pytest.fixture
def entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=dict(ENTRY_DATA), unique_id=f"{HOST}:8765", title="Ultimate Updater")


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
