"""配置流程：手机号 + 验证码登录保利云，选中家庭并验证网关后保存。"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .cloud_login import (
    CODE_BAD_VERIFY,
    CODE_EXPIRED_VERIFY,
    CODE_SEND_LIMIT,
    CloudError,
    list_homes,
    login,
    new_session_id,
    register_session,
    send_code,
)
from .const import (
    CONF_APP_KEY,
    CONF_APP_SECRET,
    CONF_GATEWAY_HOST,
    CONF_HOST_SN,
    CONF_LOGIN_TOKEN,
    CONF_PHONE,
    CONF_SI,
    CONF_USER_UNIQUE,
    CONF_VERIFY_CODE,
    DEFAULT_APP_KEY,
    DEFAULT_APP_SECRET,
    DEFAULT_GATEWAY_HOST,
    DOMAIN,
)
from .gateway import (
    GatewayAuthFailed,
    GatewayClient,
    GatewayLoginLimit,
    GatewayUnreachable,
)
from .protocol import UiotConfig

_LOGGER = logging.getLogger(__name__)

CREDENTIAL_FIELDS = (
    CONF_GATEWAY_HOST,
    CONF_HOST_SN,
    CONF_SI,
    CONF_LOGIN_TOKEN,
    CONF_USER_UNIQUE,
    CONF_APP_KEY,
)

DEFAULTS = {
    CONF_APP_KEY: DEFAULT_APP_KEY,
    CONF_APP_SECRET: DEFAULT_APP_SECRET,
    CONF_GATEWAY_HOST: DEFAULT_GATEWAY_HOST,
}


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(name, default=defaults.get(name, "")): str for name in CREDENTIAL_FIELDS
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


async def _async_verify(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[str, dict[str, str]]:
    """连一次网关，通过返回家庭名，失败返回错误。"""
    try:
        home = await _async_probe(hass, data)
    except GatewayLoginLimit:
        return "", {"base": "login_limit"}
    except GatewayAuthFailed:
        return "", {"base": "invalid_auth"}
    except GatewayUnreachable:
        return "", {"base": "cannot_connect"}
    return home, {}


def _bootstrap(phone: str, code: str, session_id: str) -> dict[str, Any]:
    """注册 si，用验证码换登录态，取家庭列表。"""
    si = register_session(session_id)
    account = login(phone, code, si)
    token = account["token"]
    return {
        "token": token,
        "user_unique": account["userUnique"],
        "si": si,
        "homes": list_homes(token, si),
    }


class PolyHomeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._phone = ""
        self._session_id = ""
        self._token = ""
        self._user_unique = ""
        self._si = ""
        self._homes: list[dict[str, Any]] = []
        self._home: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="user", menu_options=["phone", "manual"])

    # ---------- 手机号 + 验证码 ----------
    async def async_step_phone(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = user_input[CONF_PHONE].strip()
            self._session_id = new_session_id()
            try:
                await self.hass.async_add_executor_job(send_code, phone)
            except CloudError as err:
                _LOGGER.warning("保利云下发验证码失败: %s", err)
                errors["base"] = (
                    "send_limit" if err.code == CODE_SEND_LIMIT else "cannot_send_code"
                )
            else:
                self._phone = phone
                return await self.async_step_verify()
        return self.async_show_form(
            step_id="phone",
            data_schema=vol.Schema({vol.Required(CONF_PHONE): str}),
            errors=errors,
        )

    async def async_step_verify(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                account = await self.hass.async_add_executor_job(
                    _bootstrap, self._phone, user_input[CONF_VERIFY_CODE].strip(), self._session_id
                )
            except CloudError as err:
                _LOGGER.warning("保利云登录失败: %s", err)
                errors["base"] = (
                    "invalid_code"
                    if err.code in (CODE_BAD_VERIFY, CODE_EXPIRED_VERIFY)
                    else "cannot_connect_cloud"
                )
            else:
                if not account["homes"]:
                    return self.async_abort(reason="no_home")
                self._token = account["token"]
                self._user_unique = account["user_unique"]
                self._si = account["si"]
                self._homes = account["homes"]
                if len(self._homes) == 1:
                    self._home = self._homes[0]
                    return await self.async_step_confirm()
                return await self.async_step_home()
        return self.async_show_form(
            step_id="verify",
            data_schema=vol.Schema({vol.Required(CONF_VERIFY_CODE): str}),
            errors=errors,
            description_placeholders={"phone": self._phone},
        )

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._home = next(
                home for home in self._homes if str(home.get("sn")) == user_input[CONF_HOST_SN]
            )
            return await self.async_step_confirm()
        options = [
            {"value": str(home.get("sn")), "label": home.get("homeName") or str(home.get("sn"))}
            for home in self._homes
        ]
        return self.async_show_form(
            step_id="home",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST_SN): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options, mode=selector.SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        data = {
            CONF_GATEWAY_HOST: f"{self._home.get('hostLanIp')}:1883",
            CONF_HOST_SN: self._home.get("sn", ""),
            CONF_SI: self._si,
            CONF_LOGIN_TOKEN: self._token,
            CONF_USER_UNIQUE: self._user_unique,
            CONF_APP_KEY: DEFAULT_APP_KEY,
            CONF_APP_SECRET: DEFAULT_APP_SECRET,
        }
        errors: dict[str, str] = {}
        if user_input is not None:
            home, errors = await _async_verify(self.hass, data)
            if not errors:
                return await self._async_create(data, home)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "home": self._home.get("homeName") or data[CONF_HOST_SN],
                "gateway": data[CONF_GATEWAY_HOST],
            },
        )

    # ---------- 手动填写 ----------
    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            home, errors = await _async_verify(self.hass, user_input)
            if not errors:
                return await self._async_create(user_input, home)
        return self.async_show_form(
            step_id="manual",
            data_schema=_schema(user_input or DEFAULTS),
            errors=errors,
        )

    # ---------- 公共 ----------
    async def _async_create(self, data: dict[str, Any], title: str) -> FlowResult:
        await self.async_set_unique_id(data[CONF_HOST_SN], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title or data[CONF_HOST_SN], data=data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entry = self._get_reauth_entry()
        default = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            _, errors = await _async_verify(self.hass, {**default, **user_input})
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(default),
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
            _, errors = await _async_verify(self.hass, {**defaults, **user_input})
            if not errors:
                return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(defaults), errors=errors
        )
