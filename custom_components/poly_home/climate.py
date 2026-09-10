"""485 中央空调室内机。"""

from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_HVAC
from .coordinator import PolyCoordinator
from .entity import PolyEntity, to_float

# 网关 thermostatMode 与 HA 模式的对应关系
HVAC_TO_THERMOSTAT = {
    HVACMode.COOL: "cool",
    HVACMode.HEAT: "heat",
    HVACMode.FAN_ONLY: "fan",
}
THERMOSTAT_TO_HVAC = {value: key for key, value in HVAC_TO_THERMOSTAT.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PolyCoordinator = entry.runtime_data
    async_add_entities(
        PolyClimate(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.get("deviceType") == DEVICE_TYPE_HVAC
        and "targetTemperature" in (device.get("properties") or {})
    )


class PolyClimate(PolyEntity, ClimateEntity):
    _attr_name = None
    _attr_hvac_modes = [HVACMode.OFF, *HVAC_TO_THERMOSTAT]
    _attr_fan_modes = ["low", "medium", "high", "auto"]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 16
    _attr_max_temp = 30
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: PolyCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "climate")

    @property
    def current_temperature(self) -> float | None:
        return to_float(self._props.get("currentTemperature"))

    @property
    def target_temperature(self) -> float | None:
        return to_float(self._props.get("targetTemperature"))

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._props.get("powerSwitch") != "on":
            return HVACMode.OFF
        return THERMOSTAT_TO_HVAC.get(self._props.get("thermostatMode"))

    @property
    def fan_mode(self) -> str | None:
        return self._props.get("windSpeed")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_control(self._device_id, {"powerSwitch": "off"})
            return
        await self.coordinator.async_control(
            self._device_id,
            {"powerSwitch": "on", "thermostatMode": HVAC_TO_THERMOSTAT[hvac_mode]},
        )

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_control(
            self._device_id, {"targetTemperature": str(round(temperature))}
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.async_control(self._device_id, {"windSpeed": fan_mode})

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
