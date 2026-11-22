"""Data coordinator of the Ultimate Updater integration.

One coordinator per config entry. It polls the light-weight job list (every 30 s when idle,
every 2 s while a job runs) and reads the full status of all targets every N minutes, right after
a job has finished and after every action. Actions and the collective update live here as well, so
that no two jobs are started at the same time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import UuAuthError, UuClient, UuError
from .const import (
    BULK_ALL,
    BUSY_STATES,
    CONF_ALLOW_REBOOT,
    CONF_BULK_TARGETS,
    CONF_EXCLUDE,
    CONF_POLL_BUSY,
    CONF_POLL_IDLE,
    CONF_REMOVE_STALE,
    CONF_STATUS_INTERVAL,
    DEFAULT_POLL_BUSY,
    DEFAULT_POLL_IDLE,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
    FAILURE_STATES,
    JOB_TIMEOUT_S,
    SUCCESS_STATES,
)
from .helpers import Job, Target, is_host, is_stopped, jobs_of, security_updates

_LOGGER = logging.getLogger(__name__)

type UuConfigEntry = ConfigEntry[UuCoordinator]


@dataclass
class UuData:
    """Snapshot of the Ultimate Updater state."""

    targets: dict[str, Target] = field(default_factory=dict)
    jobs: list[Job] = field(default_factory=list)
    version: dict[str, Any] = field(default_factory=dict)
    generated_at: str | None = None

    @property
    def job_running(self) -> bool:
        return any(j.get("state") in BUSY_STATES for j in self.jobs)

    def busy_jobs(self) -> list[Job]:
        return [j for j in self.jobs if j.get("state") in BUSY_STATES]

    def jobs_of(self, target_id: str) -> list[Job]:
        t = self.targets.get(target_id)
        return jobs_of(t, self.jobs) if t else []


@dataclass
class BulkRun:
    """Running collective update."""

    security_only: bool
    total: int = 0
    index: int = 0
    current: str | None = None  # target id that is being updated
    stop: bool = False


@dataclass
class BulkResult:
    ok: int = 0
    unchanged: int = 0
    failed: int = 0
    not_started: int = 0
    stopped_skipped: int = 0

    def __str__(self) -> str:
        text = f"{self.ok} ok"
        if self.unchanged:
            text += f", {self.unchanged} unchanged"
        text += f", {self.failed} failed, {self.not_started} not started"
        if self.stopped_skipped:
            text += f", {self.stopped_skipped} shut down skipped"
        return text


class UuCoordinator(DataUpdateCoordinator[UuData]):
    """Polls Ultimate Updater and runs its actions."""

    config_entry: UuConfigEntry

    def __init__(self, hass: HomeAssistant, entry: UuConfigEntry, client: UuClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=self._opt(entry, CONF_POLL_IDLE, DEFAULT_POLL_IDLE)),
        )
        self.client = client
        self._last_status = 0.0  # monotonic time of the last full status read
        self._force_status = True
        self._version: dict[str, Any] = {}
        self._targets: dict[str, Target] = {}
        self._generated_at: str | None = None
        # unit → state of the previous poll; None until the first poll (nothing is reported then)
        self._known_jobs: dict[str, str] | None = None
        self._action_lock = asyncio.Lock()
        self._job_listeners: list[Callable[[Job, Target | None], None]] = []
        self._target_listeners: list[Callable[[], None]] = []
        self.job_logs: dict[str, str] = {}
        self._log_tried: set[str] = set()
        self._no_log_permission = False
        self.bulk: BulkRun | None = None
        self.bulk_result: str | None = None

    # ── options ──
    @staticmethod
    def _opt(entry: ConfigEntry, key: str, default: Any) -> Any:
        return entry.options.get(key, default)

    def option(self, key: str, default: Any = None) -> Any:
        return self._opt(self.config_entry, key, default)

    @property
    def allow_reboot(self) -> bool:
        return bool(self.option(CONF_ALLOW_REBOOT, False))

    def is_excluded(self, t: Target) -> bool:
        return str(t.get("id")) in (self.option(CONF_EXCLUDE, []) or [])

    # ── listeners ──
    @callback
    def async_add_job_listener(self, cb: Callable[[Job, Target | None], None]) -> Callable[[], None]:
        """Called for every job that has finished (not for jobs known at startup)."""
        self._job_listeners.append(cb)
        return lambda: self._job_listeners.remove(cb)

    # ── polling ──
    async def _async_update_data(self) -> UuData:
        try:
            jobs = await self.client.get_jobs()
            prev = self.data
            busy = any(j.get("state") in BUSY_STATES for j in jobs)
            finished = self._finished_jobs(jobs)
            status_due = time.monotonic() - self._last_status >= 60 * float(
                self.option(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
            )
            # a job that has finished changes counters/reboot flags → read the status right away
            if self._force_status or status_due or finished or (prev and prev.job_running and not busy):
                status = await self.client.get_status()
                self._targets = {
                    str(t["id"]): t
                    for t in status.get("targets") or []
                    if isinstance(t, dict) and t.get("id") not in (None, "")
                }
                self._generated_at = status.get("generated_at")
                self._last_status = time.monotonic()
                self._force_status = False
                try:
                    self._version = await self.client.get_updater_version()
                except UuError as err:
                    _LOGGER.debug("Updater version not available: %s", err)
        except UuAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UuError as err:
            raise UpdateFailed(str(err)) from err

        await self._fetch_failure_logs(jobs)
        self._set_interval(busy)
        data = UuData(targets=self._targets, jobs=jobs, version=self._version, generated_at=self._generated_at)
        self._report_finished(finished, data)
        self._remove_stale_devices(data)
        return data

    def _set_interval(self, busy: bool) -> None:
        seconds = (
            self.option(CONF_POLL_BUSY, DEFAULT_POLL_BUSY)
            if busy or self.bulk
            else self.option(CONF_POLL_IDLE, DEFAULT_POLL_IDLE)
        )
        self.update_interval = timedelta(seconds=max(1, float(seconds)))

    def _finished_jobs(self, jobs: list[Job]) -> list[Job]:
        """Jobs that reached a final state since the previous poll."""
        known = self._known_jobs
        self._known_jobs = {str(j.get("unit")): str(j.get("state")) for j in jobs if j.get("unit")}
        if known is None:
            return []
        return [
            j
            for j in jobs
            if j.get("unit")
            and j.get("state") not in BUSY_STATES
            and (str(j["unit"]) not in known or known[str(j["unit"])] in BUSY_STATES)
        ]

    def _report_finished(self, finished: list[Job], data: UuData) -> None:
        for job in finished:
            target = data.targets.get(str(job.get("target")))
            if target is None:
                target = next((t for t in data.targets.values() if job in jobs_of(t, [job])), None)
            for cb in list(self._job_listeners):
                cb(job, target)

    async def _fetch_failure_logs(self, jobs: list[Job]) -> None:
        """Last log lines of failed jobs (each job once; needs the "logs" permission)."""
        if self._no_log_permission:
            return
        for job in jobs:
            unit = str(job.get("unit") or "")
            if not unit or job.get("state") not in FAILURE_STATES or unit in self._log_tried:
                continue
            self._log_tried.add(unit)
            try:
                self.job_logs[unit] = await self.client.get_job_log(unit)
            except UuAuthError:
                self._no_log_permission = True
                _LOGGER.info('The API token has no "logs" permission – logs of failed jobs are not fetched')
                return
            except UuError as err:
                _LOGGER.debug("Log of job %s not available: %s", unit, err)
        units = {str(j.get("unit")) for j in jobs}
        for unit in [u for u in self.job_logs if u not in units]:
            del self.job_logs[unit]

    def _remove_stale_devices(self, data: UuData) -> None:
        """Devices of targets that Ultimate Updater no longer reports (e.g. deleted in Proxmox)."""
        if not data.targets or not self.option(CONF_REMOVE_STALE, True):
            return
        registry = dr.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        for device in dr.async_entries_for_config_entry(registry, entry_id):
            for domain, ident in device.identifiers:
                if domain != DOMAIN or not ident.startswith(f"{entry_id}_"):
                    continue
                if ident.removeprefix(f"{entry_id}_") not in data.targets:
                    _LOGGER.info("Removing %s: no longer reported by Ultimate Updater", device.name)
                    registry.async_update_device(device.id, remove_config_entry_id=entry_id)

    async def async_refresh_status(self) -> None:
        """Read the full status at the next poll and poll right away."""
        self._force_status = True
        await self.async_request_refresh()

    # ── actions ──
    async def _run_action(self, fn: Callable[[], Awaitable[Any]]) -> None:
        """Starts a job unless one is running (Ultimate Updater runs one job at a time)."""
        if self.bulk:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="bulk_running")
        async with self._action_lock:
            try:
                jobs = await self.client.get_jobs()
                if any(j.get("state") in BUSY_STATES for j in jobs):
                    raise HomeAssistantError(translation_domain=DOMAIN, translation_key="job_running")
                await fn()
            except UuError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="permission_denied" if err.status == 403 else "action_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
        self._set_interval(True)
        await self.async_refresh_status()

    def _target(self, target_id: str) -> Target:
        t = self.data.targets.get(target_id) if self.data else None
        if t is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_target",
                translation_placeholders={"target": target_id},
            )
        return t

    async def async_check(self, target_id: str) -> None:
        t = self._target(target_id)
        if is_host(t):
            await self._run_action(lambda: self.client.check_node(str(t.get("node"))))
        else:
            await self._run_action(lambda: self.client.check(target_id))

    async def async_update(self, target_id: str) -> None:
        """Hosts via node update (guests are not touched)."""
        t = self._target(target_id)
        if is_host(t):
            await self._run_action(lambda: self.client.update_node(str(t.get("node"))))
        else:
            await self._run_action(lambda: self.client.update(target_id))

    async def async_reboot(self, target_id: str) -> None:
        self._target(target_id)
        if not self.allow_reboot:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="reboot_disabled")
        await self._run_action(lambda: self.client.reboot(target_id))

    async def async_check_all(self) -> None:
        await self._run_action(self.client.check_all)

    async def async_cancel_jobs(self) -> None:
        """Requests cancellation of all running jobs."""
        try:
            for job in self.data.busy_jobs() if self.data else []:
                await self.client.cancel_job(str(job.get("unit")))
        except UuError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="permission_denied" if err.status == 403 else "action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.async_request_refresh()

    # ── collective update ──
    def bulk_candidates(self, targets: list[Target], security_only: bool) -> tuple[list[Target], int]:
        """VMs/CTs for a collective update and the number of shut down ones left out."""
        candidates = [
            t
            for t in targets
            if not is_host(t) and not self.is_excluded(t) and (not security_only or (security_updates(t) or 0) > 0)
        ]
        if self.option(CONF_BULK_TARGETS) == BULK_ALL:
            return candidates, 0
        # "running" (default): Ultimate Updater only updates shut down guests if STOPPED_CONTAINER /
        # STOPPED_VM is enabled in its update.conf, otherwise the job fails
        running = [t for t in candidates if not is_stopped(t)]
        return running, len(candidates) - len(running)

    async def async_start_bulk(self, security_only: bool) -> None:
        if self.bulk:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="bulk_running")
        if self.data and self.data.job_running:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="job_running")
        self.bulk = BulkRun(security_only=security_only)
        self.bulk_result = None
        self.async_update_listeners()
        self.config_entry.async_create_background_task(self.hass, self._run_bulk(self.bulk), f"{DOMAIN}_bulk_update")

    @callback
    def async_stop_bulk(self) -> None:
        if self.bulk:
            self.bulk.stop = True
            _LOGGER.info("Collective update will stop after the current target")

    async def _wait_for_jobs(self, unit: str | None = None) -> str:
        """Waits until no job is running (or the given job has finished); returns its final state."""
        deadline = time.monotonic() + JOB_TIMEOUT_S
        missing = 0
        while True:
            jobs = await self.client.get_jobs()
            if unit:
                job = next((j for j in jobs if j.get("unit") == unit), None)
                if job and job.get("state") not in BUSY_STATES:
                    return str(job.get("state"))
                missing = missing + 1 if job is None else 0
                if missing >= 3:  # a job that does not appear (anymore) counts as finished
                    return "unknown"
            elif not any(j.get("state") in BUSY_STATES for j in jobs):
                return ""
            if time.monotonic() > deadline:
                raise UuError(f"job {unit or ''} did not finish within 3 hours")
            await asyncio.sleep(max(1, float(self.option(CONF_POLL_BUSY, DEFAULT_POLL_BUSY))))

    async def _run_bulk(self, bulk: BulkRun) -> None:
        """Updates the VMs/CTs one after the other: Ultimate Updater answers 202 when a job has
        started, so the next update is only started when the previous job has finished."""
        result = BulkResult()
        label = "Update of the VMs/CTs with security updates" if bulk.security_only else "Update of all VMs/CTs"
        try:
            status = await self.client.get_status()
            targets = [t for t in status.get("targets") or [] if isinstance(t, dict) and t.get("id")]
            todo, result.stopped_skipped = self.bulk_candidates(targets, bulk.security_only)
            bulk.total = len(todo)
            _LOGGER.info("%s: %d targets, one after the other", label, len(todo))
            for i, t in enumerate(todo):
                name = t.get("name") or t.get("id")
                if bulk.stop:
                    result.not_started = len(todo) - i
                    _LOGGER.info("%s stopped – %d targets not updated", label, result.not_started)
                    break
                bulk.index, bulk.current = i + 1, str(t["id"])
                self.async_update_listeners()
                # another job (e.g. started in the Web UI) must not overlap with ours
                await self._wait_for_jobs()
                try:
                    res = await self.client.update(str(t["id"]))
                except UuError as err:
                    result.failed += 1
                    _LOGGER.warning("Update of %s could not be started: %s", name, err)
                    continue
                await self.async_request_refresh()
                unit = str(res.get("job") or "") if isinstance(res, dict) else ""
                state = await self._wait_for_jobs(unit or None)
                if not unit or state in (*SUCCESS_STATES, "unknown"):
                    result.ok += 1
                elif state == "skipped":
                    result.unchanged += 1
                else:
                    result.failed += 1
                _LOGGER.info("Update of %s: %s (%d/%d)", name, state or "finished", i + 1, len(todo))
            _LOGGER.info("%s finished: %s", label, result)
        except asyncio.CancelledError:
            _LOGGER.info("%s aborted: integration is unloading", label)
            raise
        except UuError as err:
            _LOGGER.error("%s aborted: %s", label, err)
        finally:
            self.bulk = None
            self.bulk_result = str(result)
        await self.async_refresh_status()
