"""Command acknowledgement and user-facing error helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import (
    SentrymoApiError,
    SentrymoAuthError,
    SentrymoCannotConnect,
    SentrymoEntitlementUnavailable,
    SentrymoRateLimited,
    SentrymoVehicleUnavailable,
)


def command_status(response: Mapping[str, Any]) -> str:
    """Return the normalized command acknowledgement status."""
    value = response.get("status")
    return value.strip().lower() if isinstance(value, str) else ""


def protection_update_was_accepted(response: Mapping[str, Any]) -> bool:
    """Return true when the server accepted a protection-mode change."""
    return response.get("ok") is True and command_status(response) == "accepted"


def output_update_was_confirmed(response: Mapping[str, Any]) -> bool:
    """Return true only for a physically confirmed output state.

    The current API returns `queued`, so output switches intentionally wait for
    a later read snapshot instead of claiming that the hardware already changed.
    """
    return response.get("ok") is True and command_status(response) in {
        "confirmed",
        "completed",
        "succeeded",
    }


def command_error_translation_key(err: SentrymoApiError) -> str:
    """Map a command failure to a localized Home Assistant exception key."""
    by_code = {
        "missing_cpin": "command_missing_cpin",
        "invalid_cpin": "command_invalid_cpin",
        "cpin_locked": "command_cpin_locked",
        "output_not_configured": "command_output_not_configured",
        "vehicle_unavailable": "command_vehicle_unavailable",
        "permission_denied": "command_permission_denied",
        "commands_disabled": "command_commands_disabled",
        "unsupported_command": "command_unsupported",
        "rate_limited": "command_rate_limited",
    }
    if err.code in by_code:
        return by_code[err.code]
    if isinstance(err, SentrymoAuthError):
        return "command_authentication_required"
    if isinstance(err, SentrymoEntitlementUnavailable):
        return "command_entitlement_unavailable"
    if isinstance(err, SentrymoVehicleUnavailable):
        return "command_vehicle_unavailable"
    if isinstance(err, SentrymoRateLimited):
        return "command_rate_limited"
    if isinstance(err, SentrymoCannotConnect) or err.retryable:
        return "command_temporarily_unavailable"
    return "command_failed"
