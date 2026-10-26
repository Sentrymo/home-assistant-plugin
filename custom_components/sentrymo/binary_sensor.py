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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import SentrymoDataUpdateCoordinator
from .entity import SentrymoEntity
from .places import vehicle_places

_PLACES_STORAGE_VERSION = 1
_PLACES_SAVE_DELAY = 10


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
        always_create=True,
        icon_fn=lambda value: "mdi:alarm-light" if value else "mdi:alarm-light-off",
        value_fn=lambda vehicle: _state(vehicle).get("alarm_active"),
    ),
    SentrymoBinarySensorDescription(
        key="crash_detected",
        translation_key="crash_detected",
        always_create=True,
        icon_fn=lambda value: "mdi:car-emergency" if value else "mdi:car-outline",
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

    # The API only reports places the vehicle is in right now. Remember every
    # place seen so its binary sensor exists (and is "off") after a restart
    # while the vehicle is elsewhere.
    places_store: Store[dict[str, Any]] = Store(
        hass, _PLACES_STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.places"
    )
    stored = await places_store.async_load() or {}
    stored_vehicles = stored.get("vehicles", {}) if isinstance(stored, dict) else {}
    known_places: dict[str, dict[str, dict[str, Any]]] = {
        str(vehicle_id): {
            str(key): dict(place)
            for key, place in places.items()
            if isinstance(place, dict) and place.get("name")
        }
        for vehicle_id, places in stored_vehicles.items()
        if isinstance(places, dict)
    }
    entity_registry = er.async_get(hass)

    def _should_create(
        vehicle: dict[str, Any],
        description: SentrymoBinarySensorDescription,
    ) -> bool:
        return description.always_create or description.value_fn(vehicle) is not None

    def _build_entities() -> list[BinarySensorEntity]:
        entities: list[BinarySensorEntity] = []
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

            entities.extend(_build_place_entities(vehicle, vehicle_id_str))
        return entities

    def _build_place_entities(
        vehicle: dict[str, Any], vehicle_id: str
    ) -> list[SentrymoPlaceBinarySensor]:
        vehicle_known = known_places.setdefault(vehicle_id, {})
        current = vehicle_places(vehicle) or []
        changed = False
        for place in current:
            remembered = {"id": place["id"], "name": place["name"]}
            if vehicle_known.get(place["key"]) != remembered:
                vehicle_known[place["key"]] = remembered
                changed = True
        if changed:
            places_store.async_delay_save(
                lambda: {"vehicles": known_places}, _PLACES_SAVE_DELAY
            )

        current_keys = {place["key"] for place in current}
        entities: list[SentrymoPlaceBinarySensor] = []
        for key, place in vehicle_known.items():
            marker = (vehicle_id, f"place_{key}")
            if marker in known_entity_keys:
                continue
            entity = SentrymoPlaceBinarySensor(
                coordinator, vehicle_id, key, str(place["name"]), place.get("id")
            )
            # A remembered place whose entity the user deleted is only
            # recreated once the vehicle is in that place again.
            if key not in current_keys and entity_registry.async_get_entity_id(
                "binary_sensor", DOMAIN, entity.unique_id
            ) is None:
                continue
            known_entity_keys.add(marker)
            entities.append(entity)
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


class SentrymoPlaceBinarySensor(SentrymoEntity, BinarySensorEntity):
    """On while the vehicle is inside one Sentrymo place."""

    _attr_has_entity_name = True
    _attr_translation_key = "place"

    def __init__(
        self,
        coordinator: SentrymoDataUpdateCoordinator,
        vehicle_id: str,
        place_key: str,
        place_name: str,
        place_id: Any,
    ) -> None:
        """Initialize the place binary sensor."""
        super().__init__(coordinator, vehicle_id, f"place_{place_key}")
        self.place_key = place_key
        self._place_name = place_name
        self._place_id = place_id
        self._attr_translation_placeholders = {"place": place_name}

    @property
    def is_on(self) -> bool | None:
        """Return true while the vehicle is inside the place."""
        places = vehicle_places(self.vehicle)
        if places is None:
            return None
        for place in places:
            if place["key"] == self.place_key:
                self._place_name = place["name"]
                return True
        return False

    @property
    def icon(self) -> str:
        """Return a marker icon reflecting presence."""
        return "mdi:map-marker-check" if self.is_on else "mdi:map-marker-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return place identity for templates and automations."""
        return {"place_id": self._place_id, "place_name": self._place_name}
