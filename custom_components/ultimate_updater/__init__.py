"""Ultimate Updater integration: update status of Proxmox hosts, LXC containers and VMs.

Client for the integration API v1 of BassT23's Ultimate Updater (https://github.com/BassT23/Proxmox).
Ultimate Updater does the actual work on the Proxmox cluster; this integration only reads its
status and triggers the actions it offers. Nothing is ever updated or rebooted automatically.
"""

from __future__ import annotations

from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UuClient
from .const import CONF_VALIDATE_CERT, DEFAULT_PORT, DOMAIN
from .coordinator import UuConfigEntry, UuCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.UPDATE,
]


def create_client(hass: HomeAssistant, data: dict) -> UuClient:
    return UuClient(
        async_get_clientsession(hass),
        data[CONF_HOST],
        data.get(CONF_PORT, DEFAULT_PORT),
        data[CONF_API_TOKEN],
        validate_certificate=data.get(CONF_VALIDATE_CERT, False),
    )


async def async_setup_entry(hass: HomeAssistant, entry: UuConfigEntry) -> bool:
    coordinator = UuCoordinator(hass, entry, create_client(hass, dict(entry.data)))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: UuConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: UuConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: UuConfigEntry, device: dr.DeviceEntry) -> bool:
    """A target device can be deleted by hand once Ultimate Updater no longer reports it."""
    coordinator = entry.runtime_data
    for domain, ident in device.identifiers:
        if domain != DOMAIN:
            continue
        if ident == entry.entry_id:
            return False  # the instance itself
        if ident.removeprefix(f"{entry.entry_id}_") in coordinator.data.targets:
            return False
    return True
