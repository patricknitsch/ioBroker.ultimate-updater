"""Event entity: fires when a check/update/reboot job of Ultimate Updater has finished."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import JOB_EVENT_TYPES
from .coordinator import UuConfigEntry, UuCoordinator
from .entity import UuHubEntity
from .helpers import Job, Target

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: UuConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([UuJobEvent(entry.runtime_data)])


class UuJobEvent(UuHubEntity, EventEntity):
    """Finished jobs (also jobs started in the Web UI). Jobs known at startup are not reported."""

    _attr_event_types = JOB_EVENT_TYPES

    def __init__(self, coordinator: UuCoordinator) -> None:
        super().__init__(coordinator, "job_finished")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_job_listener(self._job_finished))

    @callback
    def _job_finished(self, job: Job, target: Target | None) -> None:
        state = str(job.get("state"))
        if state not in JOB_EVENT_TYPES:
            return
        unit = str(job.get("unit") or "")
        self._trigger_event(
            state,
            {
                "unit": unit,
                "job_type": job.get("type"),
                "target_id": job.get("target"),
                "target_name": (target.get("name") or target.get("id")) if target else job.get("target"),
                "exit_code": job.get("exit_code"),
                "log": self.coordinator.job_logs.get(unit, "")[-2000:] or None,
            },
        )
        self.async_write_ha_state()
