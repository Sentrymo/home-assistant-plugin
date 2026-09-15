"""Switch platform for Sentrymo."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .commands import command_error_translation_key, output_update_was_confirmed
from .const import DATA_COORDINATOR, DOMAIN
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


def _outputs(vehicle: dict[str, Any]) -> dict[str, Any]:
    """Return vehicle output configuration safely."""
    outputs = _state(vehicle).get("outputs", {})
    return outputs if isinstance(outputs, dict) else {}


def _output_config(vehicle: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a single output configuration safely."""
    output = _outputs(vehicle).get(key, {})
    return output if isinstance(output, dict) else {}


def _output_available(vehicle: dict[str, Any], key: str) -> bool:
    """Return true when an output is configured for the vehicle."""
    return bool(_output_config(vehicle, key).get("available"))


def _supports_output_commands(vehicle: dict[str, Any]) -> bool:
    """Return true when the backend allows command execution."""
    capabilities = _capabilities(vehicle)
    return bool(
        capabilities.get("commands_enabled")
        or capabilities.get("protection_commands")
        or capabilities.get("commands")
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Sentrymo switches."""
    coordinator: SentrymoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known_entity_keys: set[tuple[str, str]] = set()

    def _build_entities() -> list[SentrymoOutputSwitch]:
        entities: list[SentrymoOutputSwitch] = []
        for vehicle in coordinator.vehicles:
            vehicle_id = vehicle.get("vehicle_id")
            if vehicle_id is None:
                continue
            vehicle_id_str = str(vehicle_id)

            if _output_available(vehicle, "immobilizer"):
                marker = (vehicle_id_str, "immobilizer_output")
                if marker not in known_entity_keys:
                    known_entity_keys.add(marker)
                    entities.append(SentrymoImmobilizerSwitch(coordinator, vehicle_id_str))

            if _output_available(vehicle, "accessory"):
                marker = (vehicle_id_str, "accessory_output")
                if marker not in known_entity_keys:
                    known_entity_keys.add(marker)
                    entities.append(SentrymoAccessorySwitch(coordinator, vehicle_id_str))
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


class SentrymoOutputSwitch(SentrymoEntity, SwitchEntity):
    """Base switch for commandable outputs."""

    _attr_has_entity_name = True
    output_key = ""
    state_keys: tuple[str, ...] = ()
    command_label = ""

    def __init__(
        self,
        coordinator: SentrymoDataUpdateCoordinator,
        vehicle_id: str,
        entity_key: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, vehicle_id, entity_key)
        self._attr_translation_key = entity_key

    @property
    def output_config(self) -> dict[str, Any]:
        """Return output configuration."""
        return _output_config(self.vehicle, self.output_key)

    @property
    def is_on(self) -> bool | None:
        """Return true when the output is active."""
        for key in self.state_keys:
            value = _state(self.vehicle).get(key)
            if value is not None:
                return bool(value)
        return None

    @property
    def available(self) -> bool:
        """Return switch availability."""
        return (
            super().available
            and _output_available(self.vehicle, self.output_key)
            and _supports_output_commands(self.vehicle)
            and bool(self.coordinator.client.cpin)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose backend output metadata."""
        attributes: dict[str, Any] = {}
        if (output := self.output_config.get("output")) is not None:
            attributes["output"] = output
        if (mode := self.output_config.get("mode")) is not None:
            attributes["mode"] = mode
        if (name := self.output_config.get("name")):
            attributes["backend_name"] = name
        return attributes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the output on."""
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the output off."""
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        """Send the output request and reconcile acknowledged state."""
        try:
            response = await self._async_send_command(enabled)
        except SentrymoApiError as err:
            self.coordinator.async_handle_command_error(
                err, vehicle_id=self.vehicle_id
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=command_error_translation_key(err),
            ) from err

        if output_update_was_confirmed(response):
            state_updates = {key: enabled for key in self.state_keys}
            self.coordinator.async_apply_vehicle_state(
                self.vehicle_id, **state_updates
            )
        self.hass.async_create_task(
            self.coordinator.async_refresh_after_delay(1.5)
        )

    async def _async_send_command(
        self, enabled: bool
    ) -> dict[str, Any]:
        """Send the backend command for this output."""
        raise NotImplementedError


class SentrymoImmobilizerSwitch(SentrymoOutputSwitch):
    """Switch for the immobilizer output."""

    output_key = "immobilizer"
    state_keys = ("immobilizer_active", "immo")
    command_label = "imobilizer"

    def __init__(self, coordinator: SentrymoDataUpdateCoordinator, vehicle_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, vehicle_id, "immobilizer_output")

    async def _async_send_command(
        self, enabled: bool
    ) -> dict[str, Any]:
        """Send the immobilizer command."""
        return await self.coordinator.client.async_set_immobilizer_active(
            self.vehicle_id, enabled
        )


class SentrymoAccessorySwitch(SentrymoOutputSwitch):
    """Switch for the accessory output."""

    output_key = "accessory"
    state_keys = ("accessory_active", "acc")
    command_label = "prislusenstvo"

    def __init__(self, coordinator: SentrymoDataUpdateCoordinator, vehicle_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, vehicle_id, "accessory_output")

    @property
    def name(self) -> str | None:
        """Return a backend-provided accessory name when available."""
        backend_name = self.output_config.get("name")
        if isinstance(backend_name, str) and backend_name.strip():
            return backend_name.strip()
        return None

    async def _async_send_command(
        self, enabled: bool
    ) -> dict[str, Any]:
        """Send the accessory command."""
        return await self.coordinator.client.async_set_accessory_active(
            self.vehicle_id, enabled
        )
