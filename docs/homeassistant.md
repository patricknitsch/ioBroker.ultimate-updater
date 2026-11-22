# Ultimate Updater for Home Assistant

🇩🇪 [Deutsche Version](homeassistant.de.md)

Custom integration that brings the update status of your Proxmox hosts, LXC containers and VMs from
**[Ultimate Updater](https://github.com/BassT23/Proxmox) by [@BassT23](https://github.com/BassT23)** into
Home Assistant and lets you start checks and updates. It is the Home Assistant counterpart of the ioBroker
adapter in this repository and uses the same integration API v1 – nothing is ever updated or rebooted
automatically, only when you press a button or install an update.

> **Unofficial community integration.** It is not affiliated with Ultimate Updater or Proxmox Server Solutions GmbH.

## Requirements

- Home Assistant 2025.2 or newer
- Ultimate Updater **5.2 or newer** with the Web UI enabled (default port `8765`)
- An **API token** of the integration API v1 (HTTPS only, own permissions). On the Proxmox host:
  ```bash
  ultimate-updater-api-token enable
  ultimate-updater-api-token create homeassistant --permissions read,logs,check,update,reboot,cancel
  ```
  Leave out permissions you do not want to grant (e.g. `read,logs,check` for status and checks only).

## Installation

**HACS:** HACS → ⋮ → *Custom repositories* → add the URL of this repository with type *Integration*, then
install *Ultimate Updater* and restart Home Assistant.

**Manually:** copy `custom_components/ultimate_updater` into the `custom_components` folder of your Home Assistant
configuration and restart Home Assistant.

Then add it under **Settings → Devices & services → Add integration → Ultimate Updater** and enter the address
of the Web UI and the API token. If the token is revoked later, Home Assistant asks for a new one; the address
can be changed with *Reconfigure*.

## Devices and entities

One device for the Ultimate Updater instance and one device per host / LXC container / VM.

| Per host/VM/CT | Description |
|---|---|
| `update.<name>_packages` | Pending package updates as an update entity – it shows up under **Settings → Updates**. *Install* starts the update of this system (hosts: node update, the guests are not touched). The "versions" are texts: installed `up to date`, latest e.g. `7 updates (2 security)`. |
| `sensor.<name>_security_updates`, `sensor.<name>_other_updates` | Pending updates (unknown for shut down/unreachable systems) |
| `binary_sensor.<name>_reboot_required` | The system needs a reboot |
| `button.<name>_check_for_updates` | Check this system (installs nothing) |
| `button.<name>_reboot` | Only if reboot buttons are allowed in the options; usable while a reboot is required |
| Diagnostic | Reachable, check status, last check, state of the latest job |

| Instance | Description |
|---|---|
| `sensor.ultimate_updater_security_updates` / `_other_updates` | Pending updates of all systems |
| `sensor.ultimate_updater_systems_with_updates`, `_systems_needing_a_reboot`, `_unreachable_systems` | Counts, the names are in the attribute `targets` |
| `sensor.ultimate_updater_summary` | e.g. "7 updates on 3 systems, 1 reboot required"; the attribute `report` holds the status report like the status mail of Ultimate Updater (e.g. for a notification or a Markdown card) |
| `binary_sensor.ultimate_updater_job_running` | A check/update job is running |
| `event.ultimate_updater_job_finished` | Fires when a job has finished (`completed`, `completed_with_warnings`, `skipped`, `failed`, `interrupted`), also for jobs started in the Web UI. Attributes: `target_name`, `target_id`, `unit`, `job_type`, `exit_code`, `log` (last log lines of failed jobs, needs the `logs` permission) |
| `button.ultimate_updater_check_all` | Check all systems including hosts |
| `button.ultimate_updater_update_all_vms_cts` | Update all VMs/CTs one after the other; hosts and excluded systems are skipped |
| `button.ultimate_updater_update_vms_cts_with_security_updates` | **Full** update of the VMs/CTs that have security updates (Ultimate Updater has no security-only update) |
| `button.ultimate_updater_stop_collective_update` | Stop a running collective update after the current system |
| `button.ultimate_updater_cancel_running_job` | Cancel the running job |
| `binary_sensor.ultimate_updater_collective_update_running`, `sensor.ultimate_updater_collective_update_progress` | Progress, e.g. `3/7: web`, at the end e.g. `4 ok, 1 unchanged, 1 failed, 0 not started` |
| Diagnostic | Ultimate Updater version, update of Ultimate Updater available, number of systems, time of the status |

Collective updates run one system after the other: Ultimate Updater answers as soon as a job has *started*, so
the integration waits until the job of one system has finished before it starts the next one. While a job is
running, further actions are refused.

## Options

| Option | Description |
|---|---|
| Full status refresh | Interval for reading all systems (default 60 min). After a job has finished or an action the status is read right away. |
| Job poll intervals | How often the job list is read: when idle (default 30 s) and while a job is running (default 2 s) |
| Excluded from collective updates | VMs/CTs that the collective update buttons skip (e.g. the Home Assistant VM itself) |
| Collective updates include | **Only running VMs/CTs** (default) or **all VMs/CTs** – "all" needs `STOPPED_CONTAINER` / `STOPPED_VM` in the `update.conf` of Ultimate Updater |
| Allow reboot buttons | Off by default |
| Remove systems that no longer exist | Removes the devices of systems Ultimate Updater no longer reports (on by default). Otherwise they stay unavailable and can be deleted on the device page. |

## Automation examples

Notification when a job failed (the event entity's `event_type` values are listed in its `event_types` attribute):

```yaml
alias: Ultimate Updater job failed
mode: queued
triggers:
  - trigger: event.received
    target:
      entity_id: event.ultimate_updater_job_finished
    options:
      event_type:
        - failed
        - interrupted
actions:
  - action: notify.notify
    data:
      title: "Update job {{ trigger.to_state.attributes.event_type }}"
      message: "{{ trigger.to_state.attributes.target_name }}: {{ trigger.to_state.attributes.log or '' }}"
```

On Home Assistant releases without the `event.received` trigger, use a `state` trigger on the event entity and a
`state` condition on its attribute `event_type`.

## Security

- The API token grants no Proxmox login, works over HTTPS only and carries exactly the permissions you give it.
  Revoke it on the host with `ultimate-updater-api-token revoke <id>`.
- The TLS certificate is **not validated** by default (self-signed Proxmox certificate). Enable *Validate TLS
  certificate* if the Web UI uses a trusted certificate and run it only in a trusted network.
- Diagnostics downloads contain the status of your systems but not the token.

## Development

```bash
pip install -r requirements_test.txt
pytest
```
