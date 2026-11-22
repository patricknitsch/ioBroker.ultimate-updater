"""Diagnostics of the Ultimate Updater integration (API token redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant

from .coordinator import UuConfigEntry

TO_REDACT = {CONF_API_TOKEN}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: UuConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": dict(entry.options)},
        "targets": list(data.targets.values()),
        "jobs": data.jobs,
        "version": data.version,
        "generated_at": data.generated_at,
        "bulk": None if coordinator.bulk is None else vars(coordinator.bulk),
        "bulk_result": coordinator.bulk_result,
    }
