"""Binary sensors: reboot required / reachable per target, job running, updater update."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UuConfigEntry, UuCoordinator, UuData
from .entity import UuHubEntity, UuTargetEntity
from .helpers import Target

PARALLEL_UPDATES = 0


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True, kw_only=True)
class TargetBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Target], bool | None]


@dataclass(frozen=True, kw_only=True)
class HubBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[UuData, UuCoordinator], bool | None]


TARGET_BINARY: tuple[TargetBinaryDescription, ...] = (
    TargetBinaryDescription(
        key="reboot_required",
        translation_key="reboot_required",
        value_fn=lambda t: _bool(t.get("reboot_required")),
    ),
    TargetBinaryDescription(
        key="reachable",
        translation_key="reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: _bool(t.get("reachable")),
    ),
)

HUB_BINARY: tuple[HubBinaryDescription, ...] = (
    HubBinaryDescription(
        key="job_running",
        translation_key="job_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d, _: d.job_running,
    ),
    HubBinaryDescription(
        key="bulk_active",
        translation_key="bulk_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda _, c: c.bulk is not None,
    ),
    HubBinaryDescription(
        key="updater_update",
        translation_key="updater_update",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: _bool(d.version.get("update_available")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: UuConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(UuHubBinarySensor(coordinator, d) for d in HUB_BINARY)
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = [tid for tid in coordinator.data.targets if tid not in known]
        known.update(new)
        async_add_entities(UuTargetBinarySensor(coordinator, tid, d) for tid in new for d in TARGET_BINARY)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class UuTargetBinarySensor(UuTargetEntity, BinarySensorEntity):
    entity_description: TargetBinaryDescription

    def __init__(self, coordinator: UuCoordinator, target_id: str, description: TargetBinaryDescription) -> None:
        super().__init__(coordinator, target_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        t = self.target
        return self.entity_description.value_fn(t) if t else None


class UuHubBinarySensor(UuHubEntity, BinarySensorEntity):
    entity_description: HubBinaryDescription

    def __init__(self, coordinator: UuCoordinator, description: HubBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator)
