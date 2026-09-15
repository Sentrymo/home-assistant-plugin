"""Stable Sentrymo API error contract and client-side behaviour."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class SentrymoErrorCategory(str, Enum):
    """Client-facing error categories."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    ENTITLEMENT = "entitlement"
    RESOURCE_AVAILABILITY = "resource_availability"
    CAPABILITY = "capability_scope"
    COMMAND_VALIDATION = "command_validation"
    RATE_LIMIT = "rate_limit"
    TEMPORARY = "temporary"


@dataclass(frozen=True)
class SentrymoErrorBehavior:
    """How the client must react to one stable server error code."""

    category: SentrymoErrorCategory
    reauth_required: bool = False
    invalidate_session: bool = False
    cache_allowed: bool = False
    retryable: bool = False


AUTH_REAUTH = SentrymoErrorBehavior(
    SentrymoErrorCategory.AUTHENTICATION,
    reauth_required=True,
)
AUTH_REVOKED = SentrymoErrorBehavior(
    SentrymoErrorCategory.AUTHENTICATION,
    reauth_required=True,
    invalidate_session=True,
)
AUTHORIZATION_DENIED = SentrymoErrorBehavior(SentrymoErrorCategory.AUTHORIZATION)
ENTITLEMENT_DENIED = SentrymoErrorBehavior(SentrymoErrorCategory.ENTITLEMENT)
RESOURCE_UNAVAILABLE = SentrymoErrorBehavior(
    SentrymoErrorCategory.RESOURCE_AVAILABILITY
)
CAPABILITY_DENIED = SentrymoErrorBehavior(SentrymoErrorCategory.CAPABILITY)
COMMAND_REJECTED = SentrymoErrorBehavior(SentrymoErrorCategory.COMMAND_VALIDATION)
RATE_LIMITED = SentrymoErrorBehavior(
    SentrymoErrorCategory.RATE_LIMIT,
    cache_allowed=True,
    retryable=True,
)
TEMPORARY_FAILURE = SentrymoErrorBehavior(
    SentrymoErrorCategory.TEMPORARY,
    cache_allowed=True,
    retryable=True,
)


# Keep this table in lockstep with ha-api-go/docs/API_ERROR_CONTRACT.md.
ERROR_BEHAVIORS: Final[dict[str, SentrymoErrorBehavior]] = {
    "missing_token": AUTH_REAUTH,
    "invalid_token": AUTH_REAUTH,
    "token_expired": AUTH_REAUTH,
    "invalid_setup_key": AUTH_REAUTH,
    "setup_key_expired": AUTH_REAUTH,
    "invalid_refresh_token": AUTH_REAUTH,
    "refresh_token_expired": AUTH_REAUTH,
    "integration_revoked": AUTH_REVOKED,
    "invalid_authentication": AUTH_REAUTH,
    "home_assistant_feature_unavailable": ENTITLEMENT_DENIED,
    "permission_denied": AUTHORIZATION_DENIED,
    "commands_disabled": CAPABILITY_DENIED,
    "vehicle_unavailable": RESOURCE_UNAVAILABLE,
    "unsupported_command": CAPABILITY_DENIED,
    "not_found": CAPABILITY_DENIED,
    "method_not_allowed": CAPABILITY_DENIED,
    "validation_error": COMMAND_REJECTED,
    "missing_cpin": COMMAND_REJECTED,
    "invalid_cpin": COMMAND_REJECTED,
    "output_not_configured": COMMAND_REJECTED,
    "command_failed": COMMAND_REJECTED,
    "cpin_locked": COMMAND_REJECTED,
    "rate_limited": RATE_LIMITED,
    "internal_error": TEMPORARY_FAILURE,
    "not_ready": TEMPORARY_FAILURE,
}


def behavior_for_error(code: str, path: str = "") -> SentrymoErrorBehavior:
    """Return explicit behaviour for a stable code and operation context."""
    behavior = ERROR_BEHAVIORS.get(code)
    if behavior is None:
        return TEMPORARY_FAILURE

    # The server intentionally uses permission_denied both for account
    # authorization and for a missing operation scope. Operation context lets
    # the client isolate state/command capabilities without treating either as
    # invalid authentication.
    if code == "permission_denied" and (
        "/state/" in path or "/commands/" in path
    ):
        return CAPABILITY_DENIED

    return behavior


class SentrymoApiError(Exception):
    """Base exception carrying stable, non-secret API metadata."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        status: int | None = None,
        behavior: SentrymoErrorBehavior = TEMPORARY_FAILURE,
        retry_after: int | None = None,
    ) -> None:
        """Initialize the exception."""
        super().__init__(message)
        self.code = code
        self.status = status
        self.category = behavior.category
        self.reauth_required = behavior.reauth_required
        self.invalidate_session = behavior.invalidate_session
        self.cache_allowed = behavior.cache_allowed
        self.retryable = behavior.retryable
        self.retry_after = retry_after


class SentrymoCannotConnect(SentrymoApiError):
    """Raised for a temporary network failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message, behavior=TEMPORARY_FAILURE)


class SentrymoAuthError(SentrymoApiError):
    """Base class for errors that require Home Assistant reauthentication."""


class SentrymoInvalidAuth(SentrymoAuthError):
    """Raised when credentials can no longer authenticate the integration."""


class SentrymoIntegrationRevoked(SentrymoInvalidAuth):
    """Raised when the server explicitly revoked the integration session."""


class SentrymoAuthorizationError(SentrymoApiError):
    """Raised when the authenticated account is not authorized."""


class SentrymoEntitlementUnavailable(SentrymoApiError):
    """Raised when the Home Assistant feature entitlement is unavailable."""


class SentrymoVehicleUnavailable(SentrymoApiError):
    """Raised when a vehicle is outside the current authorized set."""


class SentrymoCapabilityError(SentrymoApiError):
    """Raised when an operation or scope is unavailable."""


class SentrymoCommandError(SentrymoApiError):
    """Raised when a command request is rejected or cannot be validated."""


class SentrymoRateLimited(SentrymoApiError):
    """Raised when the server asks the client to back off."""


class SentrymoTemporaryError(SentrymoApiError):
    """Raised for a temporary server-side failure."""


_CPIN_SAFE_MESSAGES: Final[dict[str, str]] = {
    "missing_cpin": "A CPIN is required for this command.",
    "invalid_cpin": "The stored CPIN was rejected.",
    "cpin_locked": "CPIN verification is temporarily locked.",
}


def safe_error_message(code: str, message: str, path: str) -> str:
    """Return an error message that cannot echo a CPIN value."""
    if code in _CPIN_SAFE_MESSAGES:
        return _CPIN_SAFE_MESSAGES[code]
    return message or f"Unexpected Sentrymo API error for {path}"


def exception_for_error(
    *,
    code: str,
    message: str,
    status: int,
    path: str,
) -> SentrymoApiError:
    """Build the correct client exception from the stable server code."""
    behavior = behavior_for_error(code, path)
    safe_message = safe_error_message(code, message, path)
    kwargs = {"code": code, "status": status, "behavior": behavior}

    if code == "integration_revoked":
        return SentrymoIntegrationRevoked(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.AUTHENTICATION:
        return SentrymoInvalidAuth(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.AUTHORIZATION:
        return SentrymoAuthorizationError(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.ENTITLEMENT:
        return SentrymoEntitlementUnavailable(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.RESOURCE_AVAILABILITY:
        return SentrymoVehicleUnavailable(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.CAPABILITY:
        return SentrymoCapabilityError(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.COMMAND_VALIDATION:
        return SentrymoCommandError(safe_message, **kwargs)
    if behavior.category is SentrymoErrorCategory.RATE_LIMIT:
        return SentrymoRateLimited(safe_message, **kwargs)
    return SentrymoTemporaryError(safe_message, **kwargs)
