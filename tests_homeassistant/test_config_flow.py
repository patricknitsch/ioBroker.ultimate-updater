"""Config, reauth and options flow."""

from __future__ import annotations

from http import HTTPStatus

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.ultimate_updater.const import CONF_ALLOW_REBOOT, CONF_EXCLUDE, DOMAIN

from .conftest import ENTRY_DATA, FakeUu, setup_entry


async def test_user_flow(hass: HomeAssistant, fake_uu: FakeUu) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(ENTRY_DATA))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == "192.0.2.10:8765"


async def test_user_flow_invalid_auth(hass: HomeAssistant, fake_uu: FakeUu) -> None:
    fake_uu.status = HTTPStatus.UNAUTHORIZED
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(ENTRY_DATA))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    fake_uu.status = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(ENTRY_DATA))
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    import re

    from aiohttp import ClientError

    aioclient_mock.get(re.compile("/api/v1/"), exc=ClientError())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(ENTRY_DATA))
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(hass: HomeAssistant, fake_uu: FakeUu, entry) -> None:
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(ENTRY_DATA))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, fake_uu: FakeUu, entry) -> None:
    fake_uu.status = HTTPStatus.UNAUTHORIZED
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1 and flows[0]["step_id"] == "reauth_confirm"

    fake_uu.status = None
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"api_token": "new-token"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_token"] == "new-token"


async def test_options_flow(hass: HomeAssistant, fake_uu: FakeUu, entry) -> None:
    await setup_entry(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    # the exclusion list offers the guests (no hosts)
    schema = result["data_schema"].schema
    exclude = next(k for k in schema if k == CONF_EXCLUDE)
    values = [o["value"] for o in schema[exclude].config["options"]]
    assert values == ["lxc:101", "lxc:103", "vm:200"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "status_interval": 30,
            "poll_idle": 10,
            "poll_busy": 2,
            CONF_EXCLUDE: ["lxc:103"],
            "bulk_targets": "running",
            CONF_ALLOW_REBOOT: True,
            "remove_stale": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_EXCLUDE] == ["lxc:103"]
    # reloaded with reboot buttons
    assert hass.states.get("button.pve_reboot") is not None
