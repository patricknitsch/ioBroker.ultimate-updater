"""Entities, actions, collective update, job events and stale devices."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.ultimate_updater.const import CONF_ALLOW_REBOOT, CONF_EXCLUDE, DOMAIN

from .conftest import FakeUu, setup_entry


async def _tick(hass: HomeAssistant, seconds: float = 31) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def test_entities(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    web = hass.states.get("update.web_packages")
    assert web.state == STATE_ON
    assert web.attributes["installed_version"] == "up to date"
    assert web.attributes["latest_version"] == "7 updates (2 security)"
    assert hass.states.get("update.win_packages").state == STATE_OFF

    assert hass.states.get("sensor.web_security_updates").state == "2"
    assert hass.states.get("sensor.web_other_updates").state == "5"
    assert hass.states.get("sensor.ultimate_updater_security_updates").state == "3"
    assert hass.states.get("sensor.ultimate_updater_other_updates").state == "6"
    with_updates = hass.states.get("sensor.ultimate_updater_systems_with_updates")
    assert with_updates.state == "3"
    assert with_updates.attributes["targets"] == ["web", "pve", "db"]
    summary = hass.states.get("sensor.ultimate_updater_summary")
    assert summary.state == "9 updates on 3 systems, 1 reboot required"
    assert "Updates available:" in summary.attributes["report"]
    assert hass.states.get("binary_sensor.pve_reboot_required").state == STATE_ON
    assert hass.states.get("binary_sensor.ultimate_updater_job_running").state == STATE_OFF
    assert hass.states.get("binary_sensor.ultimate_updater_ultimate_updater_update").state == STATE_ON
    assert hass.states.get("sensor.ultimate_updater_ultimate_updater_version").state == "5.2.0"
    # reboot buttons only when allowed
    assert hass.states.get("button.pve_reboot") is None

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.name for d in devices} == {"Ultimate Updater", "web", "pve", "db", "win"}


async def test_install_and_check(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)

    await hass.services.async_call("update", "install", {"entity_id": "update.web_packages"}, blocking=True)
    assert fake_uu.posts()[-1] == ("update/lxc:101", {"confirm": True})
    await hass.async_block_till_done()
    assert hass.states.get("update.web_packages").attributes["in_progress"] is True
    assert hass.states.get("binary_sensor.ultimate_updater_job_running").state == STATE_ON

    # only one job at a time
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("button", "press", {"entity_id": "button.db_check_for_updates"}, blocking=True)

    fake_uu.finish_all()
    await _tick(hass, 3)
    assert hass.states.get("update.web_packages").attributes["in_progress"] is False

    # hosts go through the node endpoints
    await hass.services.async_call("button", "press", {"entity_id": "button.pve_check_for_updates"}, blocking=True)
    assert fake_uu.posts()[-1] == ("check-node/pve", {})
    fake_uu.finish_all()
    await _tick(hass, 3)
    await hass.services.async_call("update", "install", {"entity_id": "update.pve_packages"}, blocking=True)
    assert fake_uu.posts()[-1] == ("update-node/pve", {"confirm": True})
    fake_uu.finish_all()
    await _tick(hass, 3)
    await hass.services.async_call("button", "press", {"entity_id": "button.ultimate_updater_check_all"}, blocking=True)
    assert fake_uu.posts()[-1] == ("check-all", {})


async def test_cancel(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)
    assert hass.states.get("button.ultimate_updater_cancel_running_job").state == STATE_UNAVAILABLE
    await hass.services.async_call("button", "press", {"entity_id": "button.web_check_for_updates"}, blocking=True)
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ultimate_updater_cancel_running_job"}, blocking=True
    )
    assert fake_uu.posts()[-1] == ("jobs/uu-1/cancel", {})


async def test_job_event(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)
    event = hass.states.get("event.ultimate_updater_job_finished")
    assert event.attributes["event_type"] is None  # the failed job of the history is not reported

    await hass.services.async_call("button", "press", {"entity_id": "button.web_check_for_updates"}, blocking=True)
    fake_uu.finish_all("failed")
    await _tick(hass, 3)
    event = hass.states.get("event.ultimate_updater_job_finished")
    assert event.attributes["event_type"] == "failed"
    assert event.attributes["target_name"] == "web"
    assert event.attributes["log"] == "E: apt failed"


async def test_bulk_update(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_EXCLUDE: ["lxc:103"], "poll_busy": 1})
    await setup_entry(hass, entry)
    fake_uu.auto_complete = True

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ultimate_updater_update_all_vms_cts"}, blocking=True
    )
    for _ in range(20):
        await _tick(hass, 2)
        if hass.states.get("binary_sensor.ultimate_updater_collective_update_running").state == STATE_OFF:
            break
    # host skipped, lxc:103 excluded, one after the other
    assert [p for p, _ in fake_uu.posts()] == ["update/lxc:101", "update/vm:200"]
    assert (
        hass.states.get("sensor.ultimate_updater_collective_update_progress").state == "2 ok, 0 failed, 0 not started"
    )


async def test_bulk_security_only(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    fake_uu.targets[0]["skip_reason"] = {"code": "STOPPED_READ_ONLY"}  # web is shut down
    await setup_entry(hass, entry)
    fake_uu.auto_complete = True
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ultimate_updater_update_vms_cts_with_security_updates"}, blocking=True
    )
    for _ in range(20):
        await _tick(hass, 3)
        if hass.states.get("binary_sensor.ultimate_updater_collective_update_running").state == STATE_OFF:
            break
    assert [p for p, _ in fake_uu.posts()] == ["update/lxc:103"]
    assert hass.states.get("sensor.ultimate_updater_collective_update_progress").state == (
        "1 ok, 0 failed, 0 not started, 1 shut down skipped"
    )


async def test_reboot(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_REBOOT: True})
    await setup_entry(hass, entry)
    assert hass.states.get("button.web_reboot").state == STATE_UNAVAILABLE  # no reboot needed
    await hass.services.async_call("button", "press", {"entity_id": "button.pve_reboot"}, blocking=True)
    assert fake_uu.posts()[-1] == ("reboot/host:pve", {"confirm": True})


async def test_new_and_stale_targets(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)
    fake_uu.targets = [t for t in fake_uu.targets if t["id"] != "lxc:103"]
    fake_uu.targets.append({"id": "lxc:104", "name": "dns", "type": "lxc", "node": "pve", "reachable": True,
                            "security_updates": 0, "normal_updates": 0, "check_status": "ok"})  # fmt: skip
    coordinator = entry.runtime_data
    await coordinator.async_refresh_status()
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.name for d in devices} == {"Ultimate Updater", "web", "pve", "dns", "win"}
    assert hass.states.get("update.dns_packages").state == STATE_OFF
    assert hass.states.get("update.db_packages") is None


async def test_unload(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    await setup_entry(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redacts_token(hass: HomeAssistant, fake_uu: FakeUu, entry: MockConfigEntry) -> None:
    from custom_components.ultimate_updater.diagnostics import async_get_config_entry_diagnostics

    await setup_entry(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"]["api_token"] == "**REDACTED**"
    assert len(diag["targets"]) == 4
    assert DOMAIN
