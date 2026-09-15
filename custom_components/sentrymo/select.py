"""Select platform for Sentrymo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .commands import (
    command_error_translation_key,
    protection_update_was_accepted,
)
from .const import (
    DATA_CLIENT,
    DATA_COORDINATOR,
    DOMAIN,
    PROTECTION_MODE_AUTOMATIC,
    PROTECTION_MODE_DISABLED,
    PROTECTION_MODE_MANUAL,
    PROTECTION_MODE_OPTIONS,
)
from .coordinator import SentrymoDataUpdateCoordinator
from .entity import SentrymoEntity
from .errors import SentrymoApiError


def _capabilities(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return vehicle capabilities safely."""
    capabilities = vehicle.get("capabilities", {})
    return capabilities if isinstance(capabilities, dict) else {}


def _state(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return vehicle state safely."""
    state = vehicle.get("state", {})
    return state if isinstance(state, dict) else {}


def _supports_protection_commands(vehicle: dict[str, Any]) -> bool:
    """Return true when the backend says protection mode can be changed."""
    capabilities = _capabilities(vehicle)
    return bool(
        capabilities.get("protection_commands")
        or capabilities.get("commands_enabled")
        or capabilities.get("commands")
    )


_PROTECTION_MODE_LABELS: dict[str, dict[str, str]] = {
    "sk": {
        PROTECTION_MODE_AUTOMATIC: "Automaticky",
        PROTECTION_MODE_DISABLED: "Vypnutá",
        PROTECTION_MODE_MANUAL: "Zapnutá",
    },
    "cs": {
        PROTECTION_MODE_AUTOMATIC: "Automaticky",
        PROTECTION_MODE_DISABLED: "Vypnutá",
        PROTECTION_MODE_MANUAL: "Zapnutá",
    },
    "en": {
        PROTECTION_MODE_AUTOMATIC: "Automatic",
        PROTECTION_MODE_DISABLED: "Disabled",
        PROTECTION_MODE_MANUAL: "Enabled",
    },
}


def _protection_state_updates(mode: str) -> dict[str, Any]:
    """Return optimistic state updates for a selected protection mode."""
    return {
        "protection_mode": mode,
        "protection_active": mode != PROTECTION_MODE_DISABLED,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Sentrymo selects."""
    coordinator: SentrymoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    client = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    known_vehicle_ids: set[str] = set()

    def _build_entities() -> list[SentrymoProtectionModeSelect]:
        entities: list[SentrymoProtectionModeSelect] = []
        for vehicle in coordinator.vehicles:
            vehicle_id = vehicle.get("vehicle_id")
            if vehicle_id is None:
                continue
            vehicle_id_str = str(vehicle_id)
            if vehicle_id_str in known_vehicle_ids:
                continue
            known_vehicle_ids.add(vehicle_id_str)
            entities.append(SentrymoProtectionModeSelect(coordinator, client, vehicle_id_str))
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


class SentrymoProtectionModeSelect(SentrymoEntity, SelectEntity):
    """Select vehicle protection mode."""

    _attr_has_entity_name = True
    _attr_translation_key = "protection_mode_control"
    def __init__(
        self,
        coordinator: SentrymoDataUpdateCoordinator,
        client: Any,
        vehicle_id: str,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator, vehicle_id, "protection_mode_control")
        self.client = client

    def _language(self) -> str:
        """Return the active Home Assistant language code."""
        language = str(getattr(self.hass.config, "language", "en")).lower()
        return language.replace("_", "-").split("-", maxsplit=1)[0]

    def _label_for_mode(self, mode: str) -> str:
        """Return the display label for a backend mode."""
        labels = _PROTECTION_MODE_LABELS.get(self._language(), _PROTECTION_MODE_LABELS["en"])
        return labels.get(mode, mode)

    def _mode_for_label(self, label: str) -> str | None:
        """Return the backend mode for a displayed label."""
        for language_labels in _PROTECTION_MODE_LABELS.values():
            for mode, mode_label in language_labels.items():
                if mode_label == label:
                    return mode
        return label if label in PROTECTION_MODE_OPTIONS else None

    @property
    def options(self) -> list[str]:
        """Return translated protection mode options."""
        return [self._label_for_mode(mode) for mode in PROTECTION_MODE_OPTIONS]

    @property
    def current_option(self) -> str | None:
        """Return current protection mode."""
        value = _state(self.vehicle).get("protection_mode")
        if isinstance(value, str) and value in PROTECTION_MODE_OPTIONS:
            return self._label_for_mode(value)

        if _state(self.vehicle).get("protection_active") is True:
            return self._label_for_mode(PROTECTION_MODE_MANUAL)

        if _state(self.vehicle).get("protection_active") is False:
            return self._label_for_mode(PROTECTION_MODE_DISABLED)

        return None

    @property
    def available(self) -> bool:
        """Return select availability."""
        return (
            super().available
            and _supports_protection_commands(self.vehicle)
            and bool(self.client.cpin)
        )

    async def async_select_option(self, option: str) -> None:
        """Set protection mode."""
        backend_option = self._mode_for_label(option)
        if backend_option not in PROTECTION_MODE_OPTIONS:
            return

        try:
            response = await self.client.async_set_protection_mode(
                self.vehicle_id, backend_option
            )
        except SentrymoApiError as err:
            self.coordinator.async_handle_command_error(
                err, vehicle_id=self.vehicle_id
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=command_error_translation_key(err),
            ) from err

        if protection_update_was_accepted(response):
            self.coordinator.async_apply_vehicle_state(
                self.vehicle_id,
                **_protection_state_updates(backend_option),
            )
        self.hass.async_create_task(
            self.coordinator.async_refresh_after_delay(1.5)
        )
