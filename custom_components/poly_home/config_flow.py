"""配置流程：填网关与凭据，能连上并登录才允许保存。"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_GATEWAY_HOST,
    CONF_HOST_SN,
    CONF_LOGIN_TOKEN,
    CONF_SI,
    CONF_USER_UNIQUE,
    DEFAULT_APP_KEY,
    DEFAULT_GATEWAY_HOST,
    DOMAIN,
)
from .gateway import GatewayAuthFailed, GatewayClient, GatewayUnreachable
from .protocol import UiotConfig

TEXT_FIELDS = (
    CONF_GATEWAY_HOST,
    CONF_HOST_SN,
    CONF_SI,
    CONF_LOGIN_TOKEN,
    CONF_USER_UNIQUE,
    CONF_APP_KEY,
)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(key, default=defaults.get(key, "")): str for key in TEXT_FIELDS
    }
    fields[
        vol.Required(CONF_APP_SECRET, default=defaults.get(CONF_APP_SECRET, ""))
    ] = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
    return vol.Schema(fields)


def _probe(data: dict[str, Any]) -> str:
    """连一次网关并登录，返回家庭名称。"""
    client = GatewayClient(UiotConfig(data), client_suffix="_probe")
    try:
        return client.connect()
    finally:
        client.disconnect()


async def _async_probe(hass: HomeAssistant, data: dict[str, Any]) -> str:
    return await hass.async_add_executor_job(_probe, data)


class PolyHomeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                home = await _async_probe(self.hass, user_input)
            except GatewayAuthFailed:
                errors["base"] = "invalid_auth"
            except GatewayUnreachable:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_HOST_SN])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=home or user_input[CONF_HOST_SN], data=user_input
                )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {CONF_APP_KEY: DEFAULT_APP_KEY, CONF_GATEWAY_HOST: DEFAULT_GATEWAY_HOST}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_probe(self.hass, {**entry.data, **entry.options, **user_input})
            except GatewayAuthFailed:
                errors["base"] = "invalid_auth"
            except GatewayUnreachable:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_LOGIN_TOKEN): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return PolyHomeOptionsFlow()


class PolyHomeOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self.config_entry
        defaults = {**entry.data, **entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_probe(self.hass, {**defaults, **user_input})
            except GatewayAuthFailed:
                errors["base"] = "invalid_auth"
            except GatewayUnreachable:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(defaults), errors=errors
        )
