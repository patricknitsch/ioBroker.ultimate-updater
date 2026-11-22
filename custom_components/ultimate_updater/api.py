"""Client for the integration API v1 of Ultimate Updater 5.2+.

https://github.com/BassT23/Proxmox (docs/api-v1.md)

- "Authorization: Bearer <token>", HTTPS only, endpoints below /api/v1/
- permissions per token: read, logs, check, update, reboot, cancel (403 if missing)
- update/update-node/reboot need the body {"confirm": true}, checks an empty body

The Web UI login of Ultimate Updater is deliberately not supported: its endpoints
are no stable interface and it needs the password of a Proxmox administrator.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp

TIMEOUT_S = 15


class UuError(Exception):
    """Error of an API call, carrying HTTP status and API error code."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class UuConnectionError(UuError):
    """The Web UI could not be reached."""


class UuAuthError(UuError):
    """Token missing, invalid (401) or without permission (403)."""


def _q(value: str) -> str:
    return quote(str(value), safe="")


class UuClient:
    """Async client for the Ultimate Updater integration API v1."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        token: str,
        *,
        use_https: bool = True,
        validate_certificate: bool = False,
    ) -> None:
        host = host.strip()
        if not host:
            raise ValueError("No IP address / host name configured")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"  # IPv6
        scheme = "https" if use_https else "http"
        self.base = f"{scheme}://{host}:{int(port)}"
        self._session = session
        self._token = token.strip()
        self._ssl: bool | None = None if validate_certificate else False

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}/api/v1{path}"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.request(
                method,
                url,
                json=body,
                headers=headers,
                ssl=self._ssl,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
            ) as res:
                try:
                    data = await res.json(content_type=None)
                except ValueError:
                    data = await res.text()
                status = res.status
        except (TimeoutError, aiohttp.ClientError) as err:
            raise UuConnectionError(f"{method} {path}: {err or type(err).__name__}") from err

        if status < 200 or status >= 300:
            err = data.get("error") if isinstance(data, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            msg = err.get("message") if isinstance(err, dict) else None
            text = f"{method} {path} → HTTP {status}{f': {msg}' if msg else ''}"
            if status in (401, 403):
                raise UuAuthError(text, status, code)
            raise UuError(text, status, code)
        return data

    # ── reads ──
    async def get_status(self) -> dict[str, Any]:
        """Status with targets[]."""
        data = await self._call("GET", "/status")
        return data if isinstance(data, dict) else {}

    async def get_jobs(self) -> list[dict[str, Any]]:
        """Running and recent jobs."""
        data = await self._call("GET", "/jobs")
        jobs = data.get("jobs") if isinstance(data, dict) else None
        return [j for j in jobs or [] if isinstance(j, dict)]

    async def get_job_log(self, unit: str) -> str:
        """Last log lines of a job."""
        data = await self._call("GET", f"/jobs/{_q(unit)}/log")
        return str((data or {}).get("log") or "") if isinstance(data, dict) else ""

    async def get_updater_version(self) -> dict[str, Any]:
        """Installed/available version of Ultimate Updater."""
        data = await self._call("GET", "/updater-version")
        return data if isinstance(data, dict) else {}

    # ── actions (answer 202 when the job has started) ──
    async def check(self, target_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/check/{_q(target_id)}", {})

    async def update(self, target_id: str) -> dict[str, Any]:
        return await self._call("POST", f"/update/{_q(target_id)}", {"confirm": True})

    async def check_node(self, node: str) -> dict[str, Any]:
        return await self._call("POST", f"/check-node/{_q(node)}", {})

    async def update_node(self, node: str) -> dict[str, Any]:
        return await self._call("POST", f"/update-node/{_q(node)}", {"confirm": True})

    async def reboot(self, target_id: str) -> dict[str, Any]:
        """Server only allows it when reboot_required is set."""
        return await self._call("POST", f"/reboot/{_q(target_id)}", {"confirm": True})

    async def cancel_job(self, unit: str) -> dict[str, Any]:
        return await self._call("POST", f"/jobs/{_q(unit)}/cancel", {})

    async def check_all(self) -> dict[str, Any]:
        return await self._call("POST", "/check-all", {})
