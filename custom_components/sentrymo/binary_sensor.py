"""Binary sensor platform for Sentrymo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SentrymoDataUpdateCoordinator
from .entity import SentrymoEntity


def _state(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return vehicle state safely."""
    state = vehicle.get("state", {})
    return state if isinstance(state, dict) else {}


@dataclass(frozen=True, kw_only=True)
class SentrymoBinarySensorDescription(BinarySensorEntityDescription):
    """Description for a Sentrymo binary sensor."""

    value_fn: Callable[[dict[str, Any]], Any]
    always_create: bool = False
    icon_fn: Callable[[bool | None], str | None] | None = None


BINARY_SENSOR_DESCRIPTIONS: tuple[SentrymoBinarySensorDescription, ...] = (
    SentrymoBinarySensorDescription(
        key="moving",
        translation_key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        always_create=True,
        icon="mdi:motion",
        value_fn=lambda vehicle: _state(vehicle).get("moving"),
    ),
    SentrymoBinarySensorDescription(
        key="ignition",
        translation_key="ignition",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:key-variant",
        value_fn=lambda vehicle: _state(vehicle).get("ignition"),
    ),
    SentrymoBinarySensorDescription(
        key="acc",
        translation_key="acc",
        device_class=BinarySensorDeviceClass.POWER,
        value_fn=lambda vehicle: _state(vehicle).get("acc"),
    ),
    SentrymoBinarySensorDescription(
        key="immo",
        translation_key="immo",
        icon_fn=lambda value: "mdi:lock-outline" if value else "mdi:lock-open-variant-outline",
        value_fn=lambda vehicle: _state(vehicle).get("immo"),
    ),
    SentrymoBinarySensorDescription(
        key="locked",
        translation_key="locked",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=lambda vehicle: _state(vehicle).get("locked"),
    ),
    SentrymoBinarySensorDescription(
        key="protection_active",
        translation_key="protection_active",
        always_create=True,
        icon_fn=lambda value: "mdi:shield-lock" if value else "mdi:shield-lock-open",
        value_fn=lambda vehicle: _state(vehicle).get("protection_active"),
    ),
    SentrymoBinarySensorDescription(
        key="alarm_active",
        translation_key="alarm_active",
        device_class=BinarySensorDeviceClass.PROBLEM,
        always_create=True,
        icon_fn=lambda value: "mdi:alarm-light" if value else "mdi:alarm-light-off",
        value_fn=lambda vehicle: _state(vehicle).get("alarm_active"),
    ),
    SentrymoBinarySensorDescription(
        key="crash_detected",
        translation_key="crash_detected",
        device_class=BinarySensorDeviceClass.PROBLEM,
        always_create=True,
        value_fn=lambda vehicle: _state(vehicle).get("crash_detected"),
    ),
    SentrymoBinarySensorDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        always_create=True,
        icon_fn=lambda value: "mdi:car-connected" if value else "mdi:car-off",
        value_fn=lambda vehicle: _state(vehicle).get("online"),
    ),
    SentrymoBinarySensorDescription(
        key="driving",
        translation_key="driving",
        icon="mdi:file-image-marker-outline",
        value_fn=lambda vehicle: _state(vehicle).get("driving"),
    ),
    SentrymoBinarySensorDescription(
        key="low_voltage",
        translation_key="low_voltage",
        device_class=BinarySensorDeviceClass.BATTERY,
        value_fn=lambda vehicle: _state(vehicle).get("is_low_voltage"),
    ),
    SentrymoBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_registry_enabled_default=False,
        value_fn=lambda vehicle: _state(vehicle).get("charging"),
    ),
    SentrymoBinarySensorDescription(
        key="doors_open",
        translation_key="doors_open",
        device_class=BinarySensorDeviceClass.DOOR,
        entity_registry_enabled_default=False,
        value_fn=lambda vehicle: _state(vehicle).get("doors_open"),
    ),
    SentrymoBinarySensorDescription(
        key="bt_connected",
        translation_key="bt_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_registry_enabled_default=False,
        icon_fn=lambda value: "mdi:bluetooth" if value else "mdi:bluetooth-off",
        value_fn=lambda vehicle: _state(vehicle).get("bt_connected"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Sentrymo binary sensors."""
    coordinator: SentrymoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known_entity_keys: set[tuple[str, str]] = set()

    def _should_create(
        vehicle: dict[str, Any],
        description: SentrymoBinarySensorDescription,
    ) -> bool:
        return description.always_create or description.value_fn(vehicle) is not None

    def _build_entities() -> list[SentrymoBinarySensor]:
        entities: list[SentrymoBinarySensor] = []
        for vehicle in coordinator.vehicles:
            vehicle_id = vehicle.get("vehicle_id")
            if vehicle_id is None:
                continue
            vehicle_id_str = str(vehicle_id)

            for description in BINARY_SENSOR_DESCRIPTIONS:
                if not _should_create(vehicle, description):
                    continue

                marker = (vehicle_id_str, description.key)
                if marker in known_entity_keys:
                    continue
                known_entity_keys.add(marker)
                entities.append(SentrymoBinarySensor(coordinator, vehicle_id_str, description))
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


class SentrymoBinarySensor(SentrymoEntity, BinarySensorEntity):
    """Represent a Sentrymo binary sensor."""

    entity_description: SentrymoBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SentrymoDataUpdateCoordinator,
        vehicle_id: str,
        description: SentrymoBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        value = self.entity_description.value_fn(self.vehicle)
        return None if value is None else bool(value)

    @property
    def icon(self) -> str | None:
        """Return the configured binary sensor icon."""
        value = self.is_on
        if self.entity_description.icon_fn is not None:
            return self.entity_description.icon_fn(value)
        return self.entity_description.icon
