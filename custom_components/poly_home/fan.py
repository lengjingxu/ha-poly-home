"""新风机组：只有开关与三档风速。"""

from __future__ import annotations

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_HVAC
from .coordinator import PolyCoordinator
from .entity import PolyEntity

SPEED_TO_PERCENTAGE = {"low": 33, "medium": 66, "high": 100}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PolyCoordinator = entry.runtime_data
    async_add_entities(
        PolyFan(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.get("deviceType") == DEVICE_TYPE_HVAC
        and "windSpeed" in (device.get("properties") or {})
        and "targetTemperature" not in (device.get("properties") or {})
    )


class PolyFan(PolyEntity, FanEntity):
    _attr_name = None
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: PolyCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "fan")

    @property
    def is_on(self) -> bool:
        return self._props.get("powerSwitch") == "on"

    @property
    def percentage(self) -> int | None:
        return SPEED_TO_PERCENTAGE.get(self._props.get("windSpeed"))

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs
    ) -> None:
        if percentage is None:
            await self.coordinator.async_control(self._device_id, {"powerSwitch": "on"})
            return
        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_control(self._device_id, {"powerSwitch": "off"})

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = min(SPEED_TO_PERCENTAGE, key=lambda s: abs(SPEED_TO_PERCENTAGE[s] - percentage))
        await self.coordinator.async_control(self._device_id, {"windSpeed": speed})
