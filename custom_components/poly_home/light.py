"""面板继电器控制的灯具。"""

from __future__ import annotations

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_LIGHT
from .coordinator import PolyCoordinator
from .entity import PolyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PolyCoordinator = entry.runtime_data
    async_add_entities(
        PolyLight(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.get("deviceType") == DEVICE_TYPE_LIGHT
        and "powerSwitch" in (device.get("properties") or {})
    )


class PolyLight(PolyEntity, LightEntity):
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator: PolyCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "light")

    @property
    def is_on(self) -> bool:
        return self._props.get("powerSwitch") == "on"

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_control(self._device_id, {"powerSwitch": "on"})

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_control(self._device_id, {"powerSwitch": "off"})
