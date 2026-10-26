"""Sensor platform for Sentrymo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SentrymoDataUpdateCoordinator
from .entity import SentrymoEntity
from .places import vehicle_places


def _parse_datetime(value: Any) -> datetime | None:
    """Parse datetime values safely."""
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    return value if isinstance(value, datetime) else None


def _vehicle_state(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return vehicle state dict safely."""
    state = vehicle.get("state", {})
    return state if isinstance(state, dict) else {}


def _vehicle_location(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return vehicle location dict safely."""
    location = vehicle.get("location", {})
    return location if isinstance(location, dict) else {}


def _scale_gsm_signal(value: Any) -> int | None:
    """Normalize backend GSM signal strength to the raw 0-5 scale."""
    if not isinstance(value, (int, float)):
        return None
    if value <= 5:
        return max(0, min(5, int(round(float(value)))))
    return max(0, min(5, int(round((float(value) / 100) * 5))))


def _gsm_signal_icon(vehicle: dict[str, Any]) -> str:
    """Return GSM icon for the normalized signal level."""
    level = _scale_gsm_signal(_vehicle_state(vehicle).get("gsm_signal"))
    icon_by_level = {
        0: "mdi:network-strength-off",
        1: "mdi:network-strength-1",
        2: "mdi:network-strength-2",
        3: "mdi:network-strength-3",
        4: "mdi:network-strength-4",
        5: "mdi:network-strength-4",
    }
    return icon_by_level.get(level, "mdi:network-strength-off")


def _external_voltage(vehicle: dict[str, Any]) -> float | None:
    """Return external voltage rounded to one decimal place."""
    value = _vehicle_state(vehicle).get("external_voltage")
    if not isinstance(value, (int, float)):
        return None
    return round(float(value), 1)


def _first_value(vehicle: dict[str, Any], *keys: str) -> Any:
    """Return first non-null state value by key."""
    state = _vehicle_state(vehicle)
    for key in keys:
        value = state.get(key)
        if value is not None:
            return value
    return None


def _battery_percent(vehicle: dict[str, Any]) -> Any:
    """Return internal battery percentage from the new backend fields."""
    return _first_value(
        vehicle,
        "internal_battery_percent",
        "battery_level_percent",
        "internal_battery_level",
    )


def _address(vehicle: dict[str, Any]) -> str | None:
    """Return address from location or state."""
    for source in (_vehicle_location(vehicle), _vehicle_state(vehicle)):
        value = source.get("address")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _places(vehicle: dict[str, Any]) -> str | None:
    """Return a comma separated list of place names."""
    state = _vehicle_state(vehicle)
    value = state.get("places")
    if value is None:
        value = _vehicle_location(vehicle).get("places")

    if isinstance(value, list):
        names = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(names) if names else None

    if isinstance(value, str) and value.strip():
        return value.strip()

    return None


def _places_attributes(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return place names and ids as lists for templates and conditions."""
    places = vehicle_places(vehicle)
    if places is None:
        return {}
    return {
        "places": [place["name"] for place in places],
        "place_ids": [place["id"] for place in places if place["id"] is not None],
    }


def _vehicle_status(vehicle: dict[str, Any]) -> str:
    """Build a compact text status."""
    state = _vehicle_state(vehicle)
    alarm_state = state.get("alarm_state")
    crash_state = state.get("crash_state")

    if isinstance(crash_state, str) and crash_state not in {"", "idle", "dismissed"}:
        return "crash"
    if isinstance(alarm_state, str) and alarm_state not in {"", "idle", "dismissed"}:
        return "alarm"
    if state.get("crash_detected"):
        return "crash"
    if state.get("alarm_active") and not isinstance(alarm_state, str):
        return "alarm"
    if state.get("moving"):
        return "moving"
    if state.get("ignition"):
        return "ignition_on"
    if state.get("online") is False:
        return "offline"

    return "idle"


@dataclass(frozen=True, kw_only=True)
class SentrymoSensorDescription(SensorEntityDescription):
    """Description for a Sentrymo sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    always_create: bool = False
    icon_fn: Callable[[dict[str, Any]], str | None] | None = None
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[SentrymoSensorDescription, ...] = (
    SentrymoSensorDescription(
        key="speed",
        translation_key="speed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        always_create=True,
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("speed_kmh"),
    ),
    SentrymoSensorDescription(
        key="external_voltage",
        translation_key="external_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        always_create=True,
        icon="mdi:car-battery",
        value_fn=_external_voltage,
    ),
    SentrymoSensorDescription(
        key="internal_battery",
        translation_key="internal_battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        always_create=True,
        value_fn=_battery_percent,
    ),
    SentrymoSensorDescription(
        key="gsm_signal",
        translation_key="gsm_signal",
        state_class=SensorStateClass.MEASUREMENT,
        always_create=True,
        value_fn=lambda vehicle: _scale_gsm_signal(_vehicle_state(vehicle).get("gsm_signal")),
        icon_fn=_gsm_signal_icon,
    ),
    SentrymoSensorDescription(
        key="odometer",
        translation_key="odometer",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("odometer_km"),
    ),
    SentrymoSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        always_create=True,
        value_fn=lambda vehicle: _parse_datetime(
            vehicle.get("updated_at") or _vehicle_state(vehicle).get("last_seen_at")
        ),
    ),
    SentrymoSensorDescription(
        key="vehicle_status",
        translation_key="vehicle_status",
        always_create=True,
        value_fn=_vehicle_status,
    ),
    SentrymoSensorDescription(
        key="alarm_state",
        translation_key="alarm_state",
        always_create=True,
        icon_fn=lambda vehicle: (
            "mdi:alarm-light"
            if _vehicle_state(vehicle).get("alarm_active")
            else "mdi:alarm-light-off"
        ),
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("alarm_state"),
    ),
    SentrymoSensorDescription(
        key="crash_state",
        translation_key="crash_state",
        always_create=True,
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("crash_state"),
    ),
    SentrymoSensorDescription(
        key="protection_mode",
        translation_key="protection_mode",
        always_create=True,
        icon="mdi:shield",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("protection_mode"),
    ),
    SentrymoSensorDescription(
        key="sleep_state",
        translation_key="sleep_state",
        icon="mdi:sleep",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("sleep_state"),
    ),
    SentrymoSensorDescription(
        key="gnss_state",
        translation_key="gnss_state",
        icon="mdi:crosshairs-gps",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("gnss_state"),
    ),
    SentrymoSensorDescription(
        key="data_mode",
        translation_key="data_mode",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("data_mode"),
    ),
    SentrymoSensorDescription(
        key="fuel_level",
        translation_key="fuel_level",
        native_unit_of_measurement="l",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda vehicle: _first_value(vehicle, "fuel_level_litres", "fuel_level"),
    ),
    SentrymoSensorDescription(
        key="engine_rpm",
        translation_key="engine_rpm",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        icon="mdi:turbine",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("engine_rpm"),
    ),
    SentrymoSensorDescription(
        key="engine_temperature",
        translation_key="engine_temperature",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("engine_temperature"),
    ),
    SentrymoSensorDescription(
        key="satellites",
        translation_key="satellites",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        icon="mdi:satellite-variant",
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("satellites"),
    ),
    SentrymoSensorDescription(
        key="hdop",
        translation_key="hdop",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=lambda vehicle: _vehicle_state(vehicle).get("hdop"),
    ),
    SentrymoSensorDescription(
        key="address",
        translation_key="address",
        entity_registry_enabled_default=False,
        icon="mdi:map-marker",
        value_fn=_address,
    ),
    SentrymoSensorDescription(
        key="places",
        translation_key="places",
        entity_registry_enabled_default=False,
        icon="mdi:map-legend",
        value_fn=_places,
        attributes_fn=_places_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Sentrymo sensors."""
    coordinator: SentrymoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known_entity_keys: set[tuple[str, str]] = set()

    def _should_create(vehicle: dict[str, Any], description: SentrymoSensorDescription) -> bool:
        return description.always_create or description.value_fn(vehicle) is not None

    def _build_entities() -> list[SentrymoSensor]:
        entities: list[SentrymoSensor] = []

        for vehicle in coordinator.vehicles:
            vehicle_id = vehicle.get("vehicle_id")
            if vehicle_id is None:
                continue

            vehicle_id_str = str(vehicle_id)

            for description in SENSOR_DESCRIPTIONS:
                if not _should_create(vehicle, description):
                    continue

                marker = (vehicle_id_str, description.key)
                if marker in known_entity_keys:
                    continue

                known_entity_keys.add(marker)
                entities.append(SentrymoSensor(coordinator, vehicle_id_str, description))

        return entities

    entities = _build_entities()
    if entities:
        async_add_entities(entities)

    @callback
    def _handle_coordinator_update() -> None:
        new_entities = _build_entities()
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))
    return True


class SentrymoSensor(SentrymoEntity, SensorEntity):
    """Represent a Sentrymo sensor."""

    entity_description: SentrymoSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SentrymoDataUpdateCoordinator,
        vehicle_id: str,
        description: SentrymoSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> Any:
        """Return native value."""
        return self.entity_description.value_fn(self.vehicle)

    @property
    def icon(self) -> str | None:
        """Return the configured sensor icon."""
        if self.entity_description.icon_fn is not None:
            return self.entity_description.icon_fn(self.vehicle)
        return self.entity_description.icon

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return structured attributes when the description provides them."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.vehicle)
