"""Sensors: pending updates per target and in total, summary, job state, updater version."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UuConfigEntry, UuCoordinator, UuData
from .entity import UuHubEntity, UuTargetEntity
from .helpers import (
    Target,
    available_updates,
    build_report,
    is_current,
    normal_updates,
    parse_time,
    security_updates,
    summary_text,
)

PARALLEL_UPDATES = 0


def _names(targets: list[Target]) -> list[str]:
    return [str(t.get("name") or t.get("id")) for t in targets]


@dataclass(frozen=True, kw_only=True)
class TargetSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Target, UuData], Any]


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    value_fn: Callable[[UuData, UuCoordinator], Any]
    attrs_fn: Callable[[UuData, UuCoordinator], dict[str, Any]] | None = None


def _job_state(t: Target, data: UuData) -> str:
    own = data.jobs_of(str(t.get("id")))
    return str(own[0].get("state")) if own else "none"


TARGET_SENSORS: tuple[TargetSensorDescription, ...] = (
    TargetSensorDescription(
        key="security_updates",
        translation_key="security_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t, _: security_updates(t) if is_current(t) else None,
    ),
    TargetSensorDescription(
        key="normal_updates",
        translation_key="normal_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t, _: normal_updates(t) if is_current(t) else None,
    ),
    TargetSensorDescription(
        key="check_status",
        translation_key="check_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t, _: t.get("check_status") or None,
    ),
    TargetSensorDescription(
        key="last_check",
        translation_key="last_check",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t, _: parse_time(t.get("last_check")),
    ),
    TargetSensorDescription(
        key="job_state",
        translation_key="job_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_job_state,
    ),
)


def _current(data: UuData) -> list[Target]:
    return [t for t in data.targets.values() if is_current(t)]


def _with_updates(data: UuData) -> list[Target]:
    return [t for t in _current(data) if (available_updates(t) or 0) > 0]


def _reboot(data: UuData) -> list[Target]:
    return [t for t in data.targets.values() if t.get("reboot_required") is True]


def _unreachable(data: UuData) -> list[Target]:
    return [t for t in data.targets.values() if t.get("reachable") is False]


def _bulk_progress(data: UuData, c: UuCoordinator) -> str | None:
    if c.bulk:
        t = data.targets.get(c.bulk.current or "")
        name = (t.get("name") or t.get("id")) if t else c.bulk.current
        return f"{c.bulk.index}/{c.bulk.total}: {name}" if c.bulk.total else "starting"
    return c.bulk_result


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    HubSensorDescription(
        key="security_updates_total",
        translation_key="security_updates_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: sum(security_updates(t) or 0 for t in _current(d)),
    ),
    HubSensorDescription(
        key="normal_updates_total",
        translation_key="normal_updates_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: sum(normal_updates(t) or 0 for t in _current(d)),
    ),
    HubSensorDescription(
        key="targets_with_updates",
        translation_key="targets_with_updates",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: len(_with_updates(d)),
        attrs_fn=lambda d, _: {"targets": _names(_with_updates(d))},
    ),
    HubSensorDescription(
        key="reboot_required_count",
        translation_key="reboot_required_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: len(_reboot(d)),
        attrs_fn=lambda d, _: {"targets": _names(_reboot(d))},
    ),
    HubSensorDescription(
        key="unreachable_count",
        translation_key="unreachable_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d, _: len(_unreachable(d)),
        attrs_fn=lambda d, _: {"targets": _names(_unreachable(d))},
    ),
    HubSensorDescription(
        key="summary",
        translation_key="summary",
        value_fn=lambda d, _: summary_text(list(d.targets.values())),
        attrs_fn=lambda d, _: {"report": build_report(list(d.targets.values()))},
    ),
    HubSensorDescription(
        key="bulk_progress",
        translation_key="bulk_progress",
        value_fn=_bulk_progress,
    ),
    HubSensorDescription(
        key="target_count",
        translation_key="target_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: len(d.targets),
    ),
    HubSensorDescription(
        key="updater_version",
        translation_key="updater_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: d.version.get("installed"),
        attrs_fn=lambda d, _: {"available": d.version.get("available")},
    ),
    HubSensorDescription(
        key="generated_at",
        translation_key="generated_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, _: parse_time(d.generated_at),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: UuConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(UuHubSensor(coordinator, d) for d in HUB_SENSORS)
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new = [tid for tid in coordinator.data.targets if tid not in known]
        known.update(new)
        async_add_entities(UuTargetSensor(coordinator, tid, d) for tid in new for d in TARGET_SENSORS)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


class UuTargetSensor(UuTargetEntity, SensorEntity):
    entity_description: TargetSensorDescription

    def __init__(self, coordinator: UuCoordinator, target_id: str, description: TargetSensorDescription) -> None:
        super().__init__(coordinator, target_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | datetime | None:
        t = self.target
        return self.entity_description.value_fn(t, self.coordinator.data) if t else None


class UuHubSensor(UuHubEntity, SensorEntity):
    entity_description: HubSensorDescription

    def __init__(self, coordinator: UuCoordinator, description: HubSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | datetime | None:
        value = self.entity_description.value_fn(self.coordinator.data, self.coordinator)
        if isinstance(value, str):
            return value[:255]
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data, self.coordinator) if fn else None
