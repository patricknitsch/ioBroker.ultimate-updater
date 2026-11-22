"""Config flow of the Ultimate Updater integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_API_TOKEN, CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import create_client
from .api import UuAuthError, UuConnectionError, UuError
from .const import (
    BULK_ALL,
    BULK_RUNNING,
    CONF_ALLOW_REBOOT,
    CONF_BULK_TARGETS,
    CONF_EXCLUDE,
    CONF_POLL_BUSY,
    CONF_POLL_IDLE,
    CONF_REMOVE_STALE,
    CONF_STATUS_INTERVAL,
    CONF_VALIDATE_CERT,
    DEFAULT_POLL_BUSY,
    DEFAULT_POLL_IDLE,
    DEFAULT_PORT,
    DEFAULT_STATUS_INTERVAL,
    DOMAIN,
)
from .coordinator import UuConfigEntry
from .helpers import is_host, label

_LOGGER = logging.getLogger(__name__)

TOKEN_SELECTOR = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


def _connection_schema(defaults: Mapping[str, Any], with_token: bool = True) -> vol.Schema:
    schema: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, vol.UNDEFINED)): str,
        vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
    }
    if with_token:
        schema[vol.Required(CONF_API_TOKEN)] = TOKEN_SELECTOR
    schema[vol.Required(CONF_VALIDATE_CERT, default=defaults.get(CONF_VALIDATE_CERT, False))] = bool
    return vol.Schema(schema)


class UltimateUpdaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Connection to the integration API v1 of Ultimate Updater."""

    VERSION = 1

    async def _validate(self, data: Mapping[str, Any]) -> dict[str, str]:
        try:
            await create_client(self.hass, dict(data)).get_status()
        except UuAuthError:
            return {"base": "invalid_auth"}
        except UuConnectionError:
            return {"base": "cannot_connect"}
        except UuError as err:
            _LOGGER.warning("Ultimate Updater answered with an error: %s", err)
            return {"base": "api_error"}
        except ValueError:
            return {CONF_HOST: "invalid_host"}
        except Exception:
            _LOGGER.exception("Unexpected error")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            errors = await self._validate(user_input)
            if not errors:
                return self.async_create_entry(title=f"Ultimate Updater ({user_input[CONF_HOST]})", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_connection_schema({}), user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_API_TOKEN: user_input[CONF_API_TOKEN]}
            errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): TOKEN_SELECTOR}),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_HOST] = user_input[CONF_HOST].strip()
            data = {**entry.data, **user_input}
            await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_PORT]}")
            self._abort_if_unique_id_mismatch(reason="wrong_instance")
            errors = await self._validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or entry.data, with_token=False),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: UuConfigEntry) -> OptionsFlow:
        return UltimateUpdaterOptionsFlow()


class UltimateUpdaterOptionsFlow(OptionsFlow):
    """Polling, collective updates, reboot buttons, stale devices."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        opts = self.config_entry.options
        coordinator = getattr(self.config_entry, "runtime_data", None)
        targets = coordinator.data.targets.values() if coordinator and coordinator.data else []
        guests = sorted((t for t in targets if not is_host(t)), key=lambda t: str(t.get("id")))
        excluded = list(opts.get(CONF_EXCLUDE, []))
        options = [selector.SelectOptionDict(value=str(t["id"]), label=label(t)) for t in guests]
        # keep excluded targets that are currently not reported
        options += [
            selector.SelectOptionDict(value=x, label=x) for x in excluded if x not in {o["value"] for o in options}
        ]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_STATUS_INTERVAL, default=opts.get(CONF_STATUS_INTERVAL, DEFAULT_STATUS_INTERVAL)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=1440, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_POLL_IDLE, default=opts.get(CONF_POLL_IDLE, DEFAULT_POLL_IDLE)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=3600, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_POLL_BUSY, default=opts.get(CONF_POLL_BUSY, DEFAULT_POLL_BUSY)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=60, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Optional(CONF_EXCLUDE, default=excluded): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(
                    CONF_BULK_TARGETS, default=opts.get(CONF_BULK_TARGETS, BULK_RUNNING)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[BULK_RUNNING, BULK_ALL], translation_key=CONF_BULK_TARGETS)
                ),
                vol.Required(CONF_ALLOW_REBOOT, default=opts.get(CONF_ALLOW_REBOOT, False)): bool,
                vol.Required(CONF_REMOVE_STALE, default=opts.get(CONF_REMOVE_STALE, True)): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
