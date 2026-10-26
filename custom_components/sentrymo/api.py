"""API client for the Sentrymo integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, timedelta
import logging
from typing import Any

import async_timeout
from aiohttp import ClientError, ClientResponse, ClientSession

from homeassistant.util import dt as dt_util

from .api_url import normalize_api_url as normalize_api_base_url
from .const import (
    API_AUTH_EXCHANGE,
    API_AUTH_REFRESH,
    API_PROFILE,
    API_STATE_CONFIG,
    API_STATE_FAST,
    API_STATE_SLOW,
    API_STATE_TELEMETRY,
    API_VEHICLES,
    COMMAND_ACCESSORY_ACTIVATE,
    COMMAND_ACCESSORY_DEACTIVATE,
    COMMAND_IMMOBILIZER_ACTIVATE,
    COMMAND_IMMOBILIZER_DEACTIVATE,
    COMMAND_PROTECTION_ACTIVATE,
    COMMAND_PROTECTION_AUTO,
    COMMAND_PROTECTION_DEACTIVATE,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_EXCHANGE_PAYLOAD,
    DEFAULT_PROD_API_URL,
    DEFAULT_SOURCE,
    PROTECTION_MODE_AUTOMATIC,
    PROTECTION_MODE_DISABLED,
    PROTECTION_MODE_MANUAL,
    STALE_DATA_GRACE_PERIOD,
)
from .errors import (
    AUTH_REAUTH,
    AUTHORIZATION_DENIED,
    COMMAND_REJECTED,
    ERROR_BEHAVIORS,
    RATE_LIMITED,
    RESOURCE_UNAVAILABLE,
    SentrymoApiError,
    SentrymoAuthorizationError,
    SentrymoCannotConnect,
    SentrymoCapabilityError,
    SentrymoCommandError,
    SentrymoInvalidAuth,
    SentrymoRateLimited,
    SentrymoTemporaryError,
    SentrymoVehicleUnavailable,
    exception_for_error,
    safe_error_message,
)

_LOGGER = logging.getLogger(__name__)

TokenUpdateCallback = Callable[[dict[str, str | None]], Awaitable[None]]

_REFRESHABLE_ACCESS_CODES = {
    "invalid_token",
    "token_expired",
}
_SEGMENT_PATHS = {
    "fast": API_STATE_FAST,
    "telemetry": API_STATE_TELEMETRY,
    "slow": API_STATE_SLOW,
    "config": API_STATE_CONFIG,
}

_FAST_PREFERRED_STATE_KEYS = ("address", "places", "place_details")


class SentrymoApiClient:
    """Async Sentrymo API client."""

    def __init__(
        self,
        session: ClientSession,
        api_url: str = DEFAULT_PROD_API_URL,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: str | None = None,
        cpin: str | None = None,
        *,
        token_update_callback: TokenUpdateCallback | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self.api_url = self.normalize_api_url(api_url)
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expires_at = token_expires_at
        self.cpin = cpin
        self._token_update_callback = token_update_callback
        self._segment_cache: dict[str, dict[str, Any]] = {}
        self._segment_next_refresh: dict[str, Any] = {}
        self._stale_segments: set[str] = set()
        self._segment_fetched_at: dict[str, Any] = {}

    @staticmethod
    def normalize_api_url(api_url: str | None) -> str:
        """Normalize API URL input to the dedicated `/api/v1` base."""
        return normalize_api_base_url(api_url, DEFAULT_PROD_API_URL)

    def clear_segment_cache(self, segment: str | None = None) -> None:
        """Clear all cached state segments or one selected segment."""
        if segment is None:
            self._segment_cache.clear()
            self._segment_next_refresh.clear()
            self._stale_segments.clear()
            self._segment_fetched_at.clear()
            return
        self._segment_cache.pop(segment, None)
        self._segment_next_refresh.pop(segment, None)
        self._stale_segments.discard(segment)
        self._segment_fetched_at.pop(segment, None)

    def _cached_segment_within_grace(self, segment: str) -> bool:
        """Return true while cached segment data is recent enough to show."""
        fetched_at = self._segment_fetched_at.get(segment)
        if fetched_at is None:
            return False
        return dt_util.utcnow() - fetched_at <= STALE_DATA_GRACE_PERIOD

    def set_tokens(
        self,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: str | None = None,
        access_token_expires_at: str | None = None,
    ) -> None:
        """Update in-memory tokens."""
        if access_token:
            self.access_token = access_token
        if refresh_token:
            self.refresh_token = refresh_token

        resolved_expires_at = token_expires_at or access_token_expires_at
        if resolved_expires_at:
            self.token_expires_at = resolved_expires_at

    async def async_invalidate_session(self) -> None:
        """Invalidate tokens and cached data after explicit server revocation."""
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        self.clear_segment_cache()
        if self._token_update_callback is not None:
            await self._token_update_callback(
                {
                    CONF_ACCESS_TOKEN: None,
                    CONF_REFRESH_TOKEN: None,
                    CONF_TOKEN_EXPIRES_AT: None,
                }
            )

    async def async_exchange_setup_key(
        self,
        api_url: str,
        setup_key: str,
        cpin: str,
        *,
        client_name: str | None = None,
        ha_instance_id: str | None = None,
    ) -> dict[str, Any]:
        """Exchange a one-time setup key for integration tokens."""
        self.api_url = self.normalize_api_url(api_url)
        self.cpin = cpin

        response = await self._request(
            "post",
            API_AUTH_EXCHANGE,
            json_payload={
                "setup_key": setup_key,
                "client_name": client_name,
                "ha_instance_id": ha_instance_id,
                "requested_polling": DEFAULT_EXCHANGE_PAYLOAD,
            },
            require_auth=False,
            allow_refresh=False,
        )

        tokens = self._extract_tokens(response)
        self.set_tokens(**tokens)
        return response

    async def async_refresh_token(self) -> dict[str, Any]:
        """Refresh an access token once."""
        if not self.refresh_token:
            raise SentrymoInvalidAuth(
                "Refresh token missing",
                code="invalid_refresh_token",
                behavior=AUTH_REAUTH,
            )

        response = await self._request(
            "post",
            API_AUTH_REFRESH,
            json_payload={CONF_REFRESH_TOKEN: self.refresh_token},
            require_auth=False,
            allow_refresh=False,
        )

        tokens = self._extract_tokens(response, refresh_token=self.refresh_token)
        self.set_tokens(**tokens)

        if self._token_update_callback is not None:
            await self._token_update_callback(tokens)

        return response

    async def async_get_profile(self) -> dict[str, Any]:
        """Fetch profile payload."""
        return await self._request("get", API_PROFILE)

    async def async_get_vehicles(self) -> dict[str, Any]:
        """Fetch the authoritative authorized vehicle list."""
        return await self._request("get", API_VEHICLES)

    async def async_get_snapshot(self, *, force: bool = False) -> dict[str, Any]:
        """Build a snapshot bounded by the latest authorized vehicle response."""
        polling: dict[str, int] = {}
        merged: dict[str, dict[str, Any]] = {}
        segment_status: dict[str, str] = {}
        server_time: str | None = None
        account: dict[str, Any] = {}
        capabilities: dict[str, Any] = {}

        # Profile and vehicles are mandatory authorization gates. Never replace
        # either with cached state.
        try:
            profile = await self.async_get_profile()
        except SentrymoApiError as err:
            if not err.cache_allowed:
                self.clear_segment_cache()
            raise

        if isinstance(profile, Mapping):
            profile_polling = profile.get("polling")
            if isinstance(profile_polling, Mapping):
                for key, value in profile_polling.items():
                    if isinstance(value, int):
                        polling[str(key)] = value

            profile_account = profile.get("account")
            if isinstance(profile_account, Mapping):
                account = dict(profile_account)

            profile_capabilities = profile.get("capabilities")
            if isinstance(profile_capabilities, Mapping):
                capabilities = dict(profile_capabilities)

            profile_server = profile.get("server")
            if isinstance(profile_server, Mapping):
                maybe_server_time = profile_server.get("server_time")
                if isinstance(maybe_server_time, str):
                    server_time = maybe_server_time

        try:
            vehicles_response = await self.async_get_vehicles()
        except SentrymoApiError as err:
            if not err.cache_allowed:
                self.clear_segment_cache()
            raise

        vehicles = (
            vehicles_response.get("vehicles")
            if isinstance(vehicles_response, Mapping)
            else []
        )
        if not isinstance(vehicles, list):
            vehicles = []

        for vehicle in vehicles:
            if not isinstance(vehicle, Mapping):
                continue
            vehicle_id = self._coerce_vehicle_id(vehicle)
            if vehicle_id is None:
                continue
            merged[vehicle_id] = {"vehicle_id": vehicle_id}
            self._merge_vehicle_segment(merged[vehicle_id], dict(vehicle))

        authorized_vehicle_ids = set(merged)
        self._prune_segment_cache(authorized_vehicle_ids)

        for segment, path in _SEGMENT_PATHS.items():
            used_fallback = False
            try:
                response = await self._get_segment(segment, path, force=force)
                if segment in self._stale_segments:
                    used_fallback = True
                    segment_status[segment] = "cached"
                    if not self._cached_segment_within_grace(segment):
                        self._mark_segment_unavailable(merged, segment)
            except SentrymoApiError as err:
                if err.cache_allowed:
                    cached = self._segment_cache.get(segment)
                    if cached is None:
                        segment_status[segment] = "unavailable"
                        self._mark_segment_unavailable(merged, segment)
                        continue
                    response = self._filter_segment_response(
                        cached, authorized_vehicle_ids
                    )
                    used_fallback = True
                    self._stale_segments.add(segment)
                    if (
                        isinstance(err, SentrymoRateLimited)
                        and err.retry_after is not None
                    ):
                        self._segment_next_refresh[segment] = (
                            dt_util.utcnow()
                            + timedelta(seconds=err.retry_after)
                        )
                    segment_status[segment] = "cached"
                    # A brief outage keeps the last known values available so
                    # entities do not bounce through unavailable, which would
                    # re-fire state automations (e.g. protection "off").
                    if not self._cached_segment_within_grace(segment):
                        self._mark_segment_unavailable(merged, segment)
                    _LOGGER.debug(
                        "Using non-current cached Sentrymo %s data after %s",
                        segment,
                        err.code or err.category.value,
                    )
                elif isinstance(
                    err, (SentrymoAuthorizationError, SentrymoCapabilityError)
                ):
                    # A missing read scope affects only this segment. Its cache
                    # is discarded and entities backed by it become unavailable.
                    self.clear_segment_cache(segment)
                    segment_status[segment] = "unavailable"
                    self._mark_segment_unavailable(merged, segment)
                    _LOGGER.warning(
                        "Sentrymo %s data unavailable (%s)",
                        segment,
                        err.code or err.category.value,
                    )
                    continue
                else:
                    # Entitlement, revocation and resource denials are never
                    # allowed to fall back to a previous authorization snapshot.
                    self.clear_segment_cache()
                    raise

            filtered = self._filter_segment_response(
                response, authorized_vehicle_ids
            )
            if not used_fallback:
                segment_status[segment] = "fresh"

            maybe_server_time = filtered.get("server_time")
            if isinstance(maybe_server_time, str):
                server_time = maybe_server_time

            recommended = filtered.get("recommended_poll_seconds")
            if isinstance(recommended, int):
                polling[segment] = recommended

            segment_vehicles = filtered.get("vehicles")
            if not isinstance(segment_vehicles, list):
                self._mark_segment_unavailable(merged, segment)
                segment_status[segment] = "unavailable"
                continue

            seen_vehicle_ids: set[str] = set()
            for vehicle in segment_vehicles:
                if not isinstance(vehicle, Mapping):
                    continue
                vehicle_id = self._coerce_vehicle_id(vehicle)
                if vehicle_id is None or vehicle_id not in authorized_vehicle_ids:
                    continue
                seen_vehicle_ids.add(vehicle_id)
                self._merge_vehicle_segment(
                    merged[vehicle_id], dict(vehicle), segment=segment
                )

            for vehicle_id in authorized_vehicle_ids - seen_vehicle_ids:
                self._mark_vehicle_segment_unavailable(
                    merged[vehicle_id], segment
                )

        for vehicle in merged.values():
            unavailable = vehicle.get("_unavailable_segments")
            if isinstance(unavailable, set):
                vehicle["_unavailable_segments"] = sorted(unavailable)

        return {
            "server_time": server_time,
            "polling": polling,
            "account": account,
            "capabilities": capabilities,
            "segment_status": segment_status,
            "vehicles": sorted(
                merged.values(),
                key=lambda item: str(item.get("name", item.get("vehicle_id", ""))),
            ),
        }

    async def async_send_command(
        self,
        vehicle_id: int | str,
        command: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a command; the response is an acknowledgement, not confirmation."""
        command_payload = {"source": DEFAULT_SOURCE}
        if payload:
            command_payload.update(payload)

        headers: dict[str, str] = {}
        if self.cpin:
            headers["X-Sentrymo-CPIN"] = self.cpin

        return await self._request(
            "post",
            f"/vehicles/{vehicle_id}/commands/{command}",
            json_payload=command_payload,
            headers=headers,
        )

    async def async_set_protection_mode(
        self,
        vehicle_id: int | str,
        mode: str,
    ) -> dict[str, Any]:
        """Request a protection-mode change."""
        command = {
            PROTECTION_MODE_DISABLED: COMMAND_PROTECTION_DEACTIVATE,
            PROTECTION_MODE_MANUAL: COMMAND_PROTECTION_ACTIVATE,
            PROTECTION_MODE_AUTOMATIC: COMMAND_PROTECTION_AUTO,
        }.get(mode)

        if command is None:
            raise SentrymoCommandError(
                "Unsupported protection mode.",
                code="validation_error",
                behavior=COMMAND_REJECTED,
            )

        return await self.async_send_command(
            vehicle_id, command, {"mode": mode}
        )

    async def async_set_immobilizer_active(
        self,
        vehicle_id: int | str,
        enabled: bool,
    ) -> dict[str, Any]:
        """Queue an immobilizer output command."""
        command = (
            COMMAND_IMMOBILIZER_ACTIVATE
            if enabled
            else COMMAND_IMMOBILIZER_DEACTIVATE
        )
        return await self.async_send_command(vehicle_id, command)

    async def async_set_accessory_active(
        self,
        vehicle_id: int | str,
        enabled: bool,
    ) -> dict[str, Any]:
        """Queue an accessory output command."""
        command = (
            COMMAND_ACCESSORY_ACTIVATE
            if enabled
            else COMMAND_ACCESSORY_DEACTIVATE
        )
        return await self.async_send_command(vehicle_id, command)

    async def _get_segment(
        self, segment: str, path: str, *, force: bool = False
    ) -> dict[str, Any]:
        """Fetch a state segment within its backend polling window."""
        now = dt_util.utcnow()
        next_refresh = self._segment_next_refresh.get(segment)

        if (
            segment in self._segment_cache
            and next_refresh is not None
            and now < next_refresh
            and (not force or segment in self._stale_segments)
        ):
            # A manual refresh may bypass the ordinary freshness window, but
            # never a server-mandated Retry-After backoff.
            return self._segment_cache[segment]

        headers = {"X-Sentrymo-Force-Refresh": "1"} if force else None
        request_path = f"{path}?force=1" if force and "?" not in path else path

        response = await self._request("get", request_path, headers=headers)
        self._segment_cache[segment] = response
        self._stale_segments.discard(segment)
        self._segment_fetched_at[segment] = now

        recommended = response.get("recommended_poll_seconds")
        seconds = (
            recommended
            if isinstance(recommended, int) and recommended > 0
            else DEFAULT_EXCHANGE_PAYLOAD.get(segment, 60)
        )
        self._segment_next_refresh[segment] = now + timedelta(seconds=seconds)
        return response

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        require_auth: bool = True,
        allow_refresh: bool = True,
    ) -> dict[str, Any]:
        """Execute an HTTP request using stable error codes."""
        url = f"{self.api_url}{path if path.startswith('/') else f'/{path}'}"
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if require_auth and self.access_token:
            request_headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            async with async_timeout.timeout(20):
                response = await self._session.request(
                    method.upper(),
                    url,
                    json=json_payload,
                    headers=request_headers,
                )
        except TimeoutError as err:
            raise SentrymoCannotConnect("Request timed out") from err
        except ClientError as err:
            raise SentrymoCannotConnect("Request failed") from err

        body = await self._decode_json(response)
        code = str(body.get("code") or "")

        if (
            response.status == 401
            and code in _REFRESHABLE_ACCESS_CODES
            and allow_refresh
            and require_auth
            and self.refresh_token
        ):
            _LOGGER.debug(
                "Refreshing Sentrymo access token after %s",
                code,
            )
            await self.async_refresh_token()
            return await self._request(
                method,
                path,
                json_payload=json_payload,
                headers=headers,
                require_auth=require_auth,
                allow_refresh=False,
            )

        error = self._error_for_response(response, body, path)
        if error is not None:
            if isinstance(error, SentrymoRateLimited):
                retry_after = self._retry_after_seconds(response)
                error.retry_after = retry_after
            if error.invalidate_session:
                await self.async_invalidate_session()
            raise error
        return body

    def _retry_after_seconds(
        self, response: ClientResponse
    ) -> int | None:
        """Parse a bounded numeric Retry-After response header."""
        headers = getattr(response, "headers", {})
        value = headers.get("Retry-After") if isinstance(headers, Mapping) else None
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return None
        return max(1, min(seconds, 24 * 60 * 60))

    async def _decode_json(self, response: ClientResponse) -> dict[str, Any]:
        """Decode a JSON response safely."""
        try:
            payload = await response.json(content_type=None)
        except ValueError:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _error_for_response(
        self,
        response: ClientResponse,
        body: Mapping[str, Any],
        path: str,
    ) -> SentrymoApiError | None:
        """Convert an HTTP failure to one domain exception."""
        if response.status < 400:
            return None

        base_path = path.split("?", maxsplit=1)[0]
        code = str(body.get("code") or "")
        message = self._redact_cpin(
            str(body.get("message") or "")
        )
        safe_message = safe_error_message(code, message, base_path)

        if response.status == 404 and base_path in {
            API_AUTH_EXCHANGE,
            API_AUTH_REFRESH,
        }:
            return SentrymoCannotConnect(
                "Home Assistant API endpoint was not found. Check API URL."
            )

        if (
            base_path == API_AUTH_EXCHANGE
            and response.status == 422
            and code not in {"home_assistant_feature_unavailable"}
        ):
            return SentrymoInvalidAuth(
                safe_message,
                code=code or "validation_error",
                status=response.status,
                behavior=AUTH_REAUTH,
            )

        if code in ERROR_BEHAVIORS:
            return exception_for_error(
                code=code,
                message=message,
                status=response.status,
                path=base_path,
            )

        if response.status == 401:
            return SentrymoInvalidAuth(
                safe_message,
                code=code,
                status=response.status,
                behavior=AUTH_REAUTH,
            )
        if response.status == 403:
            return SentrymoAuthorizationError(
                safe_message,
                code=code,
                status=response.status,
                behavior=AUTHORIZATION_DENIED,
            )
        if response.status == 404:
            return SentrymoVehicleUnavailable(
                safe_message,
                code=code,
                status=response.status,
                behavior=RESOURCE_UNAVAILABLE,
            )
        if response.status == 429:
            return SentrymoRateLimited(
                safe_message,
                code=code or "rate_limited",
                status=response.status,
                behavior=RATE_LIMITED,
            )
        if response.status >= 500:
            return SentrymoTemporaryError(
                safe_message,
                code=code,
                status=response.status,
            )
        if "/commands/" in base_path:
            return SentrymoCommandError(
                safe_message,
                code=code,
                status=response.status,
                behavior=COMMAND_REJECTED,
            )
        return SentrymoApiError(
            safe_message,
            code=code,
            status=response.status,
            behavior=AUTHORIZATION_DENIED,
        )

    def _redact_cpin(self, value: str) -> str:
        """Redact the configured CPIN from any server-provided text."""
        if self.cpin:
            return value.replace(self.cpin, "[REDACTED]")
        return value

    def _extract_tokens(
        self,
        payload: Mapping[str, Any],
        *,
        refresh_token: str | None = None,
    ) -> dict[str, str]:
        """Extract normalized token fields from a response payload."""
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SentrymoInvalidAuth(
                "Access token missing in response",
                code="invalid_authentication",
                behavior=AUTH_REAUTH,
            )

        resolved_refresh = payload.get("refresh_token")
        if not isinstance(resolved_refresh, str) or not resolved_refresh:
            resolved_refresh = refresh_token or self.refresh_token

        if not resolved_refresh:
            raise SentrymoInvalidAuth(
                "Refresh token missing in response",
                code="invalid_refresh_token",
                behavior=AUTH_REAUTH,
            )

        expires_at_value = (
            payload.get("access_token_expires_at") or payload.get("expires_at")
        )
        expires_at = self._normalize_expires_at(
            expires_at_value, payload.get("expires_in")
        )

        return {
            CONF_ACCESS_TOKEN: access_token,
            CONF_REFRESH_TOKEN: resolved_refresh,
            CONF_TOKEN_EXPIRES_AT: expires_at,
        }

    def _normalize_expires_at(self, expires_at: Any, expires_in: Any) -> str:
        """Normalize expiry values to an ISO UTC timestamp."""
        if isinstance(expires_at, str) and expires_at:
            parsed = dt_util.parse_datetime(expires_at)
            if parsed is not None:
                return parsed.astimezone(UTC).isoformat()

        if isinstance(expires_in, (int, float)) and expires_in > 0:
            return (
                dt_util.utcnow() + timedelta(seconds=int(expires_in))
            ).isoformat()

        return (dt_util.utcnow() + timedelta(hours=12)).isoformat()

    def _prune_segment_cache(self, authorized_vehicle_ids: set[str]) -> None:
        """Remove vehicles no longer present in the current vehicle ACL."""
        for segment, response in tuple(self._segment_cache.items()):
            self._segment_cache[segment] = self._filter_segment_response(
                response, authorized_vehicle_ids
            )

    def _filter_segment_response(
        self,
        response: Mapping[str, Any],
        authorized_vehicle_ids: set[str],
    ) -> dict[str, Any]:
        """Return a segment response containing authorized vehicles only."""
        filtered = dict(response)
        vehicles = response.get("vehicles")
        if not isinstance(vehicles, list):
            filtered["vehicles"] = []
            return filtered

        filtered["vehicles"] = [
            dict(vehicle)
            for vehicle in vehicles
            if isinstance(vehicle, Mapping)
            and self._coerce_vehicle_id(vehicle) in authorized_vehicle_ids
        ]
        return filtered

    def _mark_segment_unavailable(
        self, vehicles: Mapping[str, dict[str, Any]], segment: str
    ) -> None:
        """Mark one segment unavailable for every authorized vehicle."""
        for vehicle in vehicles.values():
            self._mark_vehicle_segment_unavailable(vehicle, segment)

    def _mark_vehicle_segment_unavailable(
        self, vehicle: dict[str, Any], segment: str
    ) -> None:
        """Mark one vehicle segment as unavailable."""
        unavailable = vehicle.setdefault("_unavailable_segments", set())
        if isinstance(unavailable, set):
            unavailable.add(segment)

    def _merge_vehicle_segment(
        self,
        target: dict[str, Any],
        vehicle: dict[str, Any],
        *,
        segment: str | None = None,
    ) -> None:
        """Merge a segment payload into a unified vehicle structure."""
        vehicle_id = self._coerce_vehicle_id(vehicle)
        if vehicle_id is None:
            return

        target["vehicle_id"] = vehicle_id
        target["updated_at"] = vehicle.get(
            "updated_at", target.get("updated_at")
        )

        name = vehicle.get("name")
        if isinstance(name, str) and name:
            target["name"] = name

        package = vehicle.get("package")
        if isinstance(package, str) and package:
            target["package"] = package

        capabilities = vehicle.get("capabilities")
        if isinstance(capabilities, Mapping):
            target.setdefault("capabilities", {})
            target["capabilities"].update(dict(capabilities))

        location = vehicle.get("location")
        if isinstance(location, Mapping):
            target.setdefault("location", {})
            target["location"].update(dict(location))

        state = vehicle.get("state")
        if isinstance(state, Mapping):
            target.setdefault("state", {})
            state_dict = dict(state)

            nested_capabilities = state_dict.pop("capabilities", None)
            if isinstance(nested_capabilities, Mapping):
                target.setdefault("capabilities", {})
                target["capabilities"].update(dict(nested_capabilities))

            nested_can = state_dict.get("can")
            if isinstance(nested_can, Mapping):
                state_dict.update(dict(nested_can))

            nested_name = state_dict.get("name")
            if isinstance(nested_name, str) and nested_name:
                target["name"] = nested_name

            nested_package = state_dict.get("package")
            if isinstance(nested_package, str) and nested_package:
                target["package"] = nested_package

            if segment == "slow":
                # The slow segment is polled every few minutes and must not
                # overwrite fresher place/address data from the fast segment,
                # otherwise place changes reach Home Assistant minutes late.
                for key in _FAST_PREFERRED_STATE_KEYS:
                    if key in target["state"]:
                        state_dict.pop(key, None)

            target["state"].update(state_dict)

        for nested_key in ("fast", "telemetry", "slow"):
            nested = vehicle.get(nested_key)
            if isinstance(nested, Mapping):
                target.setdefault("state", {})
                target["state"].update(dict(nested))

        gps = vehicle.get("gps")
        if isinstance(gps, Mapping):
            target.setdefault("location", {})
            target["location"].update(dict(gps))

    def _coerce_vehicle_id(
        self, vehicle: Mapping[str, Any]
    ) -> str | None:
        """Get vehicle id from different backend payload variants."""
        value = vehicle.get("vehicle_id", vehicle.get("id"))

        if value is None:
            state = vehicle.get("state")
            if isinstance(state, Mapping):
                value = state.get("id")

        if value is None:
            return None
        return str(value)
