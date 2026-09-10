"""门窗磁。"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_SAFEGUARD
from .coordinator import PolyCoordinator
from .entity import PolyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PolyCoordinator = entry.runtime_data
    async_add_entities(
        PolyContact(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if device.get("deviceType") == DEVICE_TYPE_SAFEGUARD
        and "contactState" in (device.get("properties") or {})
    )


class PolyContact(PolyEntity, BinarySensorEntity):
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator: PolyCoordinator, device_id: int) -> None:
        super().__init__(coordinator, device_id, "contact")

    @property
    def is_on(self) -> bool:
        return self._props.get("contactState") == "open"
