"""网关连接与状态轮询。"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, POLL_INTERVAL_SECONDS
from .gateway import GatewayAuthFailed, GatewayClient, GatewayUnreachable
from .protocol import UiotConfig

_LOGGER = logging.getLogger(__name__)


class PolyCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """持有一条网关连接，按固定间隔拉取设备状态。"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
        )
        self.gateway = GatewayClient(UiotConfig({**entry.data, **entry.options}))

    @property
    def host_sn(self) -> str:
        return self.gateway.cfg.host_sn

    async def async_connect(self) -> None:
        try:
            await self.hass.async_add_executor_job(self.gateway.connect)
        except GatewayAuthFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GatewayUnreachable as err:
            raise ConfigEntryNotReady(str(err)) from err

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.hass.async_add_executor_job(self.gateway.disconnect)

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        try:
            return await self.hass.async_add_executor_job(self.gateway.get_devices)
        except GatewayAuthFailed as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GatewayUnreachable as err:
            raise UpdateFailed(str(err)) from err

    async def async_control(self, device_id: int, properties: dict[str, Any]) -> None:
        """下发控制，先把结果写进本地状态，再拉一次网关状态覆盖。"""
        try:
            await self.hass.async_add_executor_job(
                self.gateway.control_device, device_id, properties
            )
        except (GatewayAuthFailed, GatewayUnreachable) as err:
            raise HomeAssistantError(f"保利智家控制失败: {err}") from err
        data = dict(self.data or {})
        device = dict(data.get(device_id) or {})
        device["properties"] = {**(device.get("properties") or {}), **properties}
        data[device_id] = device
        self.async_set_updated_data(data)
        self.hass.async_create_task(self._async_refresh_soon())

    async def _async_refresh_soon(self) -> None:
        await asyncio.sleep(2)
        await self.async_refresh()
