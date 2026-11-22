"""Update entity per host/VM/CT: pending package updates, install starts an update job."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UuConfigEntry, UuCoordinator
from .entity import UuTargetEntity
from .helpers import available_updates, is_busy, is_current, normal_updates, security_updates

PARALLEL_UPDATES = 0

UP_TO_DATE = "up to date"


async def async_setup_entry(
    hass: HomeAssistant, entry: UuConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = [tid for tid in coordinator.data.targets if tid not in known]
        known.update(new)
        async_add_entities(UuUpdateEntity(coordinator, tid) for tid in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class UuUpdateEntity(UuTargetEntity, UpdateEntity):
    """Pending updates of a target as a Home Assistant update entity.

    Package updates have no version number, so the "versions" are texts: the installed version is
    "up to date", the latest one e.g. "7 updates (2 security)".
    """

    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    _attr_title = "Packages"

    def __init__(self, coordinator: UuCoordinator, target_id: str) -> None:
        super().__init__(coordinator, target_id, "packages")

    @property
    def installed_version(self) -> str | None:
        t = self.target
        if t is None or not is_current(t) or available_updates(t) is None:
            return None
        return UP_TO_DATE

    @property
    def latest_version(self) -> str | None:
        t = self.target
        if self.installed_version is None or t is None:
            return None
        n = available_updates(t) or 0
        if n <= 0:
            return UP_TO_DATE
        sec = security_updates(t)
        return f"{n} update{'s' if n != 1 else ''}" + (f" ({sec} security)" if sec else "")

    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return latest_version != installed_version

    @property
    def release_summary(self) -> str | None:
        t = self.target
        if t is None:
            return None
        lines = []
        sec, normal = security_updates(t), normal_updates(t)
        if sec is not None or normal is not None:
            lines.append(f"Security updates: {sec or 0}, other updates: {normal or 0}")
        if t.get("reboot_required") is True:
            lines.append("A reboot is required.")
        if t.get("type") == "host":
            lines.append("Installs the updates of the Proxmox host only; its guests are not touched.")
        return "\n".join(lines)[:255] or None

    @property
    def in_progress(self) -> bool:
        data = self.coordinator.data
        bulk = self.coordinator.bulk
        if bulk and bulk.current == self.target_id:
            return True
        if data is None:
            return False
        # a running check is no installation; jobs without a type are counted
        return any(is_busy(j) and "check" not in str(j.get("type") or "") for j in data.jobs_of(self.target_id))

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        await self.coordinator.async_update(self.target_id)
