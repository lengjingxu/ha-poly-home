"""电池电量等只读状态。"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import PolyCoordinator
from .entity import PolyEntity, to_float


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PolyCoordinator = entry.runtime_data
    async_add_entities(
        PolyBattery(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if "batteryPercentage" in (device.get("properties") or {})
    )


class PolyBattery(PolyEntity, SensorEntity):
    _attr_name = "电池"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PolyCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "battery")

    @property
    def native_value(self) -> float | None:
        return to_float(self._props.get("batteryPercentage"))
