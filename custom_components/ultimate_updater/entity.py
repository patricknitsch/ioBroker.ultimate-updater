"""Base entities of the Ultimate Updater integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import UuCoordinator
from .helpers import Target, is_host, label

MODELS = {"host": "Proxmox host", "lxc": "LXC container", "vm": "Virtual machine"}


def hub_device(coordinator: UuCoordinator) -> DeviceInfo:
    entry = coordinator.config_entry
    version = coordinator.data.version if coordinator.data else {}
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Ultimate Updater",
        manufacturer=MANUFACTURER,
        model="Integration API v1",
        sw_version=str(version.get("installed")) if version.get("installed") else None,
        configuration_url=coordinator.client.base,
    )


class UuHubEntity(CoordinatorEntity[UuCoordinator]):
    """Entity of the Ultimate Updater instance itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UuCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = hub_device(coordinator)


class UuTargetEntity(CoordinatorEntity[UuCoordinator]):
    """Entity of a host, LXC container or VM."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: UuCoordinator, target_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.target_id = target_id
        entry_id = coordinator.config_entry.entry_id
        t = self.target or {"id": target_id}
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry_id}_{target_id}_{key}"
        ttype = str(t.get("type") or "")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{target_id}")},
            name=label(t) if is_host(t) else str(t.get("name") or label(t)),
            manufacturer="Proxmox" if ttype in MODELS else None,
            model=MODELS.get(ttype, ttype or None),
            model_id=target_id,
            sw_version=str(t["os_display"]) if t.get("os_display") else None,
            via_device=(DOMAIN, entry_id),
        )

    @property
    def target(self) -> Target | None:
        data = self.coordinator.data
        return data.targets.get(self.target_id) if data else None

    @property
    def available(self) -> bool:
        return super().available and self.target is not None
