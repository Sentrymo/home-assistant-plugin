"""Shared entity helpers for Sentrymo."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SentrymoDataUpdateCoordinator


_ENTITY_SOURCE_SEGMENTS: dict[str, tuple[str, ...]] = {
    "location": ("fast",),
    "last_update": ("fast", "telemetry", "slow"),
    "vehicle_status": ("fast",),
    "moving": ("fast",),
    "driving": ("fast",),
    "ignition": ("fast",),
    "acc": ("fast",),
    "immo": ("fast",),
    "locked": ("fast",),
    "protection_active": ("fast",),
    "protection_mode": ("fast",),
    "protection_mode_control": ("fast",),
    "alarm_active": ("fast",),
    "alarm_state": ("fast",),
    "crash_detected": ("fast",),
    "crash_state": ("fast",),
    "online": ("fast",),
    "address": ("fast", "slow"),
    "places": ("fast", "slow"),
    "speed": ("telemetry",),
    "external_voltage": ("telemetry",),
    "internal_battery": ("telemetry", "slow"),
    "gsm_signal": ("telemetry",),
    "sleep_state": ("telemetry",),
    "gnss_state": ("telemetry",),
    "data_mode": ("telemetry",),
    "engine_rpm": ("telemetry",),
    "satellites": ("telemetry",),
    "hdop": ("telemetry",),
    "low_voltage": ("telemetry",),
    "doors_open": ("telemetry",),
    "bt_connected": ("telemetry",),
    "fuel_level": ("slow",),
    "odometer": ("telemetry", "slow"),
    "engine_temperature": ("telemetry", "slow"),
    "immobilizer_output": ("fast",),
    "accessory_output": ("fast",),
}


class SentrymoEntity(CoordinatorEntity[SentrymoDataUpdateCoordinator]):
    """Base coordinator entity for Sentrymo vehicles."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SentrymoDataUpdateCoordinator,
        vehicle_id: str,
        entity_key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.vehicle_id = str(vehicle_id)
        self.entity_key = entity_key

    @property
    def vehicle(self) -> dict[str, Any]:
        """Return current vehicle data."""
        return self.coordinator.vehicle_by_id(self.vehicle_id) or {}

    @property
    def vehicle_state(self) -> dict[str, Any]:
        """Return current vehicle state."""
        state = self.vehicle.get("state", {})
        return state if isinstance(state, dict) else {}

    @property
    def vehicle_location(self) -> dict[str, Any]:
        """Return current vehicle location."""
        location = self.vehicle.get("location", {})
        return location if isinstance(location, dict) else {}

    @property
    def available(self) -> bool:
        """Return availability without presenting denied cached data as current."""
        if not self.coordinator.last_update_success or not self.vehicle:
            return False

        unavailable = self.vehicle.get("_unavailable_segments", [])
        unavailable_segments = (
            {str(segment) for segment in unavailable}
            if isinstance(unavailable, (list, set, tuple))
            else set()
        )
        source_segments = _ENTITY_SOURCE_SEGMENTS.get(self.entity_key)
        if source_segments is None and self.entity_key.startswith("place_"):
            source_segments = _ENTITY_SOURCE_SEGMENTS["places"]
        if source_segments is None:
            return True

        return any(
            segment not in unavailable_segments
            for segment in source_segments
        )

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return (
            f"sentrymo_{self.coordinator.instance_id}_"
            f"{self.vehicle_id}_{self.entity_key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the vehicle."""
        package = self.vehicle.get("package")
        model = (
            package.title()
            if isinstance(package, str) and package
            else "Vehicle"
        )
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self.coordinator.instance_id}_{self.vehicle_id}",
                )
            },
            manufacturer="Sentrymo",
            name=str(
                self.vehicle.get("name")
                or f"Vehicle {self.vehicle_id}"
            ),
            model=model,
        )
