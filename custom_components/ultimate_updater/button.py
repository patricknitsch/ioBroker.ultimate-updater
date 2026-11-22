"""Buttons: check per target, reboot (optional), check all, collective updates, stop/cancel."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UuConfigEntry, UuCoordinator
from .entity import UuHubEntity, UuTargetEntity

PARALLEL_UPDATES = 1

REBOOT_TYPES = ("host", "lxc", "vm")


@dataclass(frozen=True, kw_only=True)
class HubButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[UuCoordinator], Awaitable[None]]
    available_fn: Callable[[UuCoordinator], bool] = lambda _: True


async def _stop_bulk(c: UuCoordinator) -> None:
    c.async_stop_bulk()


HUB_BUTTONS: tuple[HubButtonDescription, ...] = (
    HubButtonDescription(
        key="check_all",
        translation_key="check_all",
        press_fn=lambda c: c.async_check_all(),
    ),
    HubButtonDescription(
        key="update_all",
        translation_key="update_all",
        press_fn=lambda c: c.async_start_bulk(security_only=False),
    ),
    HubButtonDescription(
        key="update_security",
        translation_key="update_security",
        press_fn=lambda c: c.async_start_bulk(security_only=True),
    ),
    HubButtonDescription(
        key="stop_bulk",
        translation_key="stop_bulk",
        press_fn=_stop_bulk,
        available_fn=lambda c: c.bulk is not None,
    ),
    HubButtonDescription(
        key="cancel_jobs",
        translation_key="cancel_jobs",
        press_fn=lambda c: c.async_cancel_jobs(),
        available_fn=lambda c: bool(c.data and c.data.job_running),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: UuConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(UuHubButton(coordinator, d) for d in HUB_BUTTONS)
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = [tid for tid in coordinator.data.targets if tid not in known]
        known.update(new)
        entities: list[ButtonEntity] = []
        for tid in new:
            entities.append(UuCheckButton(coordinator, tid))
            if coordinator.allow_reboot and coordinator.data.targets[tid].get("type") in REBOOT_TYPES:
                entities.append(UuRebootButton(coordinator, tid))
        async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class UuHubButton(UuHubEntity, ButtonEntity):
    entity_description: HubButtonDescription

    def __init__(self, coordinator: UuCoordinator, description: HubButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.coordinator)

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator)


class UuCheckButton(UuTargetEntity, ButtonEntity):
    """Checks this host/VM/CT for updates (installs nothing)."""

    def __init__(self, coordinator: UuCoordinator, target_id: str) -> None:
        super().__init__(coordinator, target_id, "check")

    async def async_press(self) -> None:
        await self.coordinator.async_check(self.target_id)


class UuRebootButton(UuTargetEntity, ButtonEntity):
    """Reboots this host/VM/CT – only available while it needs a reboot."""

    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: UuCoordinator, target_id: str) -> None:
        super().__init__(coordinator, target_id, "reboot")

    @property
    def available(self) -> bool:
        t = self.target
        return super().available and t is not None and t.get("reboot_required") is True

    async def async_press(self) -> None:
        await self.coordinator.async_reboot(self.target_id)
