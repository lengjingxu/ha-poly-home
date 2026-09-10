"""实体基类：从轮询数据里取自身设备。"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PolyCoordinator


class PolyEntity(CoordinatorEntity[PolyCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PolyCoordinator, device_id: int, suffix: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{coordinator.host_sn}_{device_id}_{suffix}"

    @property
    def _device(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(self._device_id, {})

    @property
    def _props(self) -> dict[str, Any]:
        return self._device.get("properties") or {}

    @property
    def available(self) -> bool:
        return super().available and self._device_id in (self.coordinator.data or {})

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.host_sn}_{self._device_id}")},
            name=device.get("deviceName") or f"设备 {self._device_id}",
            manufacturer="保利智家",
            model=device.get("deviceModel"),
            sw_version=device.get("softwareVersion"),
        )


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
