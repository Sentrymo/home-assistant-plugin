"""Sentrymo Home Assistant integration."""

from __future__ import annotations

from collections.abc import Iterable

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import SentrymoApiClient
from .commands import (
    command_error_translation_key,
    output_update_was_confirmed,
    protection_update_was_accepted,
)
from .const import (
    ATTR_ENABLED,
    ATTR_ENTRY_ID,
    ATTR_MODE,
    ATTR_VEHICLE_ID,
    CONF_ACCESS_TOKEN,
    CONF_API_URL,
    CONF_CPIN,
    CONF_REFRESH_TOKEN,
    CONF_SETUP_KEY,
    CONF_TOKEN_EXPIRES_AT,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_SERVICES_REGISTERED,
    DOMAIN,
    PLATFORMS,
    PROTECTION_MODE_DISABLED,
    PROTECTION_MODE_OPTIONS,
    SERVICE_REFRESH,
    SERVICE_SET_ACCESSORY,
    SERVICE_SET_IMMOBILIZER,
    SERVICE_SET_PROTECTION_MODE,
)
from .coordinator import SentrymoDataUpdateCoordinator
from .errors import SentrymoApiError, SentrymoInvalidAuth


def _protection_state_updates(mode: str) -> dict[str, bool | str]:
    """Return optimistic state updates for a selected protection mode."""
    return {
        "protection_mode": mode,
        "protection_active": mode != PROTECTION_MODE_DISABLED,
    }


def _command_home_assistant_error(
    err: SentrymoApiError,
) -> HomeAssistantError:
    """Build a localized, non-secret command exception."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=command_error_translation_key(err),
    )


def _missing_cpin_error() -> HomeAssistantError:
    """Build the localized missing-CPIN exception."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_missing_cpin",
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration domain."""
    del config
    hass.data.setdefault(DOMAIN, {})
    return True


def _migrate_api_url(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Move persisted entries from the Laravel API to the dedicated HA API."""
    configured_url = entry.options.get(CONF_API_URL, entry.data.get(CONF_API_URL))
    normalized_url = SentrymoApiClient.normalize_api_url(configured_url)
    data = dict(entry.data)
    options = dict(entry.options)
    changed = False

    if data.get(CONF_API_URL) != normalized_url:
        data[CONF_API_URL] = normalized_url
        changed = True
    if CONF_API_URL in options and options[CONF_API_URL] != normalized_url:
        options[CONF_API_URL] = normalized_url
        changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, data=data, options=options)
    return normalized_url


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Sentrymo from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    await _async_migrate_entity_identity_scope(hass, entry)
    api_url = _migrate_api_url(hass, entry)

    async def _async_update_tokens(
        tokens: dict[str, str | None],
    ) -> None:
        data = dict(entry.data)
        for key, value in tokens.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        hass.config_entries.async_update_entry(entry, data=data)

    client = SentrymoApiClient(
        async_get_clientsession(hass),
        api_url=api_url,
        access_token=entry.data.get(CONF_ACCESS_TOKEN),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        token_expires_at=entry.data.get(CONF_TOKEN_EXPIRES_AT),
        cpin=entry.data.get(CONF_CPIN),
        token_update_callback=_async_update_tokens,
    )
    try:
        await _async_restore_tokens(entry, client, hass)
    except SentrymoInvalidAuth as err:
        raise ConfigEntryAuthFailed from err

    coordinator = SentrymoDataUpdateCoordinator(hass, client, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Sentrymo config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not [key for key in hass.data[DOMAIN] if key != DATA_SERVICES_REGISTERED]:
            await _async_unregister_services(hass)
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload only when an option changes the selected API endpoint."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    client = (
        entry_data.get(DATA_CLIENT)
        if isinstance(entry_data, dict)
        else None
    )
    configured_url = entry.options.get(
        CONF_API_URL, entry.data.get(CONF_API_URL)
    )
    if (
        isinstance(client, SentrymoApiClient)
        and client.api_url
        == SentrymoApiClient.normalize_api_url(configured_url)
    ):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_restore_tokens(
    entry: ConfigEntry,
    client: SentrymoApiClient,
    hass: HomeAssistant,
) -> None:
    """Restore missing tokens for legacy entries before the first refresh."""
    if client.access_token:
        return

    if client.refresh_token:
        await client.async_refresh_token()
        return

    setup_key = entry.data.get(CONF_SETUP_KEY)
    if not isinstance(setup_key, str) or not setup_key:
        return

    await client.async_exchange_setup_key(
        entry.options.get(CONF_API_URL, entry.data[CONF_API_URL]),
        setup_key,
        str(entry.data.get(CONF_CPIN) or ""),
        client_name=str(entry.title or "Sentrymo"),
    )

    data = dict(entry.data)
    data.update(
        {
            CONF_API_URL: client.api_url,
            CONF_ACCESS_TOKEN: client.access_token,
            CONF_REFRESH_TOKEN: client.refresh_token,
            CONF_TOKEN_EXPIRES_AT: client.token_expires_at,
        }
    )
    hass.config_entries.async_update_entry(entry, data=data)


async def _async_migrate_entity_identity_scope(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate legacy entity and device identifiers to entry-scoped values."""
    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if not entity_entry.unique_id.startswith("sentrymo_"):
            continue
        if entity_entry.unique_id.startswith(f"sentrymo_{entry.entry_id}_"):
            continue
        entity_registry.async_update_entity(
            entity_entry.entity_id,
            new_unique_id=entity_entry.unique_id.replace(
                "sentrymo_",
                f"sentrymo_{entry.entry_id}_",
                1,
            ),
        )

    device_registry = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        updated_identifiers = {
            (
                identifier_domain,
                identifier_value
                if identifier_domain != DOMAIN or identifier_value.startswith(f"{entry.entry_id}_")
                else f"{entry.entry_id}_{identifier_value}",
            )
            for identifier_domain, identifier_value in device_entry.identifiers
        }
        if updated_identifiers != device_entry.identifiers:
            device_registry.async_update_device(
                device_entry.id,
                new_identifiers=updated_identifiers,
            )


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register services once per domain."""
    if hass.data[DOMAIN].get(DATA_SERVICES_REGISTERED):
        return

    async def async_handle_refresh(call: ServiceCall) -> None:
        for coordinator in _iter_coordinators(hass, call.data.get(ATTR_ENTRY_ID)):
            await coordinator.async_force_refresh()

    async def async_handle_set_protection_mode(call: ServiceCall) -> None:
        vehicle_id = str(call.data[ATTR_VEHICLE_ID])
        mode = str(call.data[ATTR_MODE])
        matching_entries = _matching_entries_for_vehicle(
            hass,
            vehicle_id,
            call.data.get(ATTR_ENTRY_ID),
        )

        if not matching_entries:
            return

        if call.data.get(ATTR_ENTRY_ID) is None and len(matching_entries) > 1:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_vehicle_ambiguous",
            )

        for data in matching_entries:
            coordinator = data[DATA_COORDINATOR]
            client = data[DATA_CLIENT]
            if not client.cpin:
                raise _missing_cpin_error()
            try:
                response = await client.async_set_protection_mode(
                    vehicle_id, mode
                )
            except SentrymoApiError as err:
                coordinator.async_handle_command_error(
                    err, vehicle_id=vehicle_id
                )
                raise _command_home_assistant_error(err) from err
            if protection_update_was_accepted(response):
                coordinator.async_apply_vehicle_state(
                    vehicle_id,
                    **_protection_state_updates(mode),
                )
            hass.async_create_task(
                coordinator.async_refresh_after_delay(1.5)
            )
            return

    async def async_handle_set_immobilizer(call: ServiceCall) -> None:
        vehicle_id = str(call.data[ATTR_VEHICLE_ID])
        enabled = bool(call.data[ATTR_ENABLED])
        matching_entries = _matching_entries_for_vehicle(
            hass,
            vehicle_id,
            call.data.get(ATTR_ENTRY_ID),
        )

        if not matching_entries:
            return

        if call.data.get(ATTR_ENTRY_ID) is None and len(matching_entries) > 1:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_vehicle_ambiguous",
            )

        for data in matching_entries:
            coordinator = data[DATA_COORDINATOR]
            client = data[DATA_CLIENT]
            if not client.cpin:
                raise _missing_cpin_error()
            try:
                response = await client.async_set_immobilizer_active(
                    vehicle_id, enabled
                )
            except SentrymoApiError as err:
                coordinator.async_handle_command_error(
                    err, vehicle_id=vehicle_id
                )
                raise _command_home_assistant_error(err) from err
            if output_update_was_confirmed(response):
                coordinator.async_apply_vehicle_state(
                    vehicle_id,
                    immobilizer_active=enabled,
                    immo=enabled,
                )
            hass.async_create_task(
                coordinator.async_refresh_after_delay(1.5)
            )
            return

    async def async_handle_set_accessory(call: ServiceCall) -> None:
        vehicle_id = str(call.data[ATTR_VEHICLE_ID])
        enabled = bool(call.data[ATTR_ENABLED])
        matching_entries = _matching_entries_for_vehicle(
            hass,
            vehicle_id,
            call.data.get(ATTR_ENTRY_ID),
        )

        if not matching_entries:
            return

        if call.data.get(ATTR_ENTRY_ID) is None and len(matching_entries) > 1:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_vehicle_ambiguous",
            )

        for data in matching_entries:
            coordinator = data[DATA_COORDINATOR]
            client = data[DATA_CLIENT]
            if not client.cpin:
                raise _missing_cpin_error()
            try:
                response = await client.async_set_accessory_active(
                    vehicle_id, enabled
                )
            except SentrymoApiError as err:
                coordinator.async_handle_command_error(
                    err, vehicle_id=vehicle_id
                )
                raise _command_home_assistant_error(err) from err
            if output_update_was_confirmed(response):
                coordinator.async_apply_vehicle_state(
                    vehicle_id,
                    accessory_active=enabled,
                    acc=enabled,
                )
            hass.async_create_task(
                coordinator.async_refresh_after_delay(1.5)
            )
            return

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        async_handle_refresh,
        schema=vol.Schema({vol.Optional(ATTR_ENTRY_ID): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROTECTION_MODE,
        async_handle_set_protection_mode,
        schema=vol.Schema(
            {
                vol.Required(ATTR_VEHICLE_ID): vol.Coerce(str),
                vol.Required(ATTR_MODE): vol.In(PROTECTION_MODE_OPTIONS),
                vol.Optional(ATTR_ENTRY_ID): str,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_IMMOBILIZER,
        async_handle_set_immobilizer,
        schema=vol.Schema(
            {
                vol.Required(ATTR_VEHICLE_ID): vol.Coerce(str),
                vol.Required(ATTR_ENABLED): cv.boolean,
                vol.Optional(ATTR_ENTRY_ID): str,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ACCESSORY,
        async_handle_set_accessory,
        schema=vol.Schema(
            {
                vol.Required(ATTR_VEHICLE_ID): vol.Coerce(str),
                vol.Required(ATTR_ENABLED): cv.boolean,
                vol.Optional(ATTR_ENTRY_ID): str,
            }
        ),
    )
    hass.data[DOMAIN][DATA_SERVICES_REGISTERED] = True


async def _async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister services when no entries remain."""
    for service in (
        SERVICE_REFRESH,
        SERVICE_SET_PROTECTION_MODE,
        SERVICE_SET_IMMOBILIZER,
        SERVICE_SET_ACCESSORY,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
    hass.data[DOMAIN].pop(DATA_SERVICES_REGISTERED, None)


def _matching_entries_for_vehicle(
    hass: HomeAssistant,
    vehicle_id: str,
    target_entry_id: str | None = None,
) -> list[dict]:
    """Return entries that contain the requested vehicle."""
    return [
        data
        for data in _iter_entry_data(hass, target_entry_id)
        if data[DATA_COORDINATOR].vehicle_by_id(vehicle_id) is not None
    ]


def _iter_coordinators(
    hass: HomeAssistant,
    target_entry_id: str | None = None,
) -> Iterable[SentrymoDataUpdateCoordinator]:
    """Yield coordinators for configured entries."""
    for data in _iter_entry_data(hass, target_entry_id):
        coordinator = data.get(DATA_COORDINATOR)
        if isinstance(coordinator, SentrymoDataUpdateCoordinator):
            yield coordinator


def _iter_entry_data(
    hass: HomeAssistant,
    target_entry_id: str | None = None,
) -> Iterable[dict]:
    """Yield stored entry data for configured entries."""
    for entry_id, data in hass.data.get(DOMAIN, {}).items():
        if entry_id == DATA_SERVICES_REGISTERED:
            continue
        if target_entry_id is not None and entry_id != target_entry_id:
            continue
        if isinstance(data, dict):
            yield data
