"""Diagnostics support with credential redaction."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CPIN,
    CONF_REFRESH_TOKEN,
    CONF_SETUP_KEY,
    CONF_TOKEN_EXPIRES_AT,
    DATA_COORDINATOR,
    DOMAIN,
)

_TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    CONF_SETUP_KEY,
    CONF_CPIN,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return non-sensitive integration diagnostics."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    data = coordinator.data if isinstance(coordinator.data, dict) else {}

    return {
        "config_entry": async_redact_data(dict(entry.data), _TO_REDACT),
        "options": async_redact_data(dict(entry.options), _TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "segment_status": data.get("segment_status", {}),
            "access_status": data.get("access_status", {}),
            "vehicle_count": len(coordinator.vehicles),
        },
    }
