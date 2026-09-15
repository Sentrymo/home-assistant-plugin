"""Data coordinators for the Sentrymo integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SentrymoApiClient
from .const import DEFAULT_POLL_INTERVAL, DOMAIN, MIN_POLL_INTERVAL
from .errors import (
    SentrymoApiError,
    SentrymoEntitlementUnavailable,
    SentrymoInvalidAuth,
    SentrymoRateLimited,
    SentrymoVehicleUnavailable,
)

_LOGGER = logging.getLogger(__name__)

_ENTITLEMENT_RECHECK_INTERVAL = timedelta(hours=1)


class SentrymoDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate Sentrymo snapshot updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SentrymoApiClient,
        instance_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_POLL_INTERVAL,
        )
        self.client = client
        self.instance_id = instance_id

    def async_apply_vehicle_state(
        self, vehicle_id: str | int, **state_updates: Any
    ) -> None:
        """Apply a server-accepted local state update for a vehicle."""
        current = self.data or {}
        vehicles = current.get("vehicles")
        if not isinstance(vehicles, list):
            return

        target = str(vehicle_id)
        updated_vehicles: list[dict[str, Any]] = []
        changed = False

        for vehicle in vehicles:
            if not isinstance(vehicle, dict):
                updated_vehicles.append(vehicle)
                continue

            if str(vehicle.get("vehicle_id")) != target:
                updated_vehicles.append(vehicle)
                continue

            updated_vehicle = dict(vehicle)
            state = updated_vehicle.get("state", {})
            updated_state = dict(state) if isinstance(state, dict) else {}
            updated_state.update(state_updates)
            updated_vehicle["state"] = updated_state
            updated_vehicles.append(updated_vehicle)
            changed = True

        if not changed:
            return

        snapshot = dict(current)
        snapshot["vehicles"] = updated_vehicles
        self.async_set_updated_data(snapshot)

    def async_handle_command_error(
        self,
        err: SentrymoApiError,
        *,
        vehicle_id: str | int | None = None,
    ) -> None:
        """Apply command failures without damaging unrelated read access."""
        if isinstance(err, SentrymoEntitlementUnavailable):
            snapshot = self._entitlement_unavailable_snapshot(err)
            self.async_set_updated_data(snapshot)
            return

        if isinstance(err, SentrymoVehicleUnavailable):
            self.client.clear_segment_cache()
            self._discard_vehicle(vehicle_id)
            return

        if err.code in {"commands_disabled", "permission_denied"}:
            self._disable_command_entities()
            return

        if not err.reauth_required:
            return

        self._discard_current_snapshot(err)
        entry = self.hass.config_entries.async_get_entry(self.instance_id)
        if entry is not None:
            entry.async_start_reauth(self.hass)

    async def async_refresh_after_delay(self, delay_seconds: float) -> None:
        """Refresh after a short delay to reconcile an acknowledged command."""
        await asyncio.sleep(delay_seconds)
        await self.async_force_refresh()

    @property
    def vehicles(self) -> list[dict[str, Any]]:
        """Return vehicles from the last authorized snapshot."""
        data = self.data or {}
        vehicles = data.get("vehicles", [])
        return vehicles if isinstance(vehicles, list) else []

    def vehicle_by_id(
        self, vehicle_id: str | int
    ) -> dict[str, Any] | None:
        """Find a vehicle by id in the current authorized snapshot."""
        target = str(vehicle_id)
        return next(
            (
                vehicle
                for vehicle in self.vehicles
                if str(vehicle.get("vehicle_id")) == target
            ),
            None,
        )

    async def async_force_refresh(self) -> None:
        """Force a manual refresh without bypassing authorization gates."""
        try:
            snapshot = await self.client.async_get_snapshot(force=True)
        except SentrymoInvalidAuth as err:
            self._clear_entitlement_issue()
            self._discard_current_snapshot(err)
            raise ConfigEntryAuthFailed from err
        except SentrymoEntitlementUnavailable as err:
            snapshot = self._entitlement_unavailable_snapshot(err)
        except SentrymoApiError as err:
            self._clear_entitlement_issue()
            self._apply_server_backoff(err)
            self._discard_if_access_denied(err)
            raise UpdateFailed(self._update_error_message(err)) from err
        else:
            self._clear_entitlement_issue()
            self.update_interval = self._parse_update_interval(snapshot)

        self.async_set_updated_data(snapshot)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch fresh data from the Sentrymo API."""
        try:
            snapshot = await self.client.async_get_snapshot()
        except SentrymoInvalidAuth as err:
            self._clear_entitlement_issue()
            self._discard_current_snapshot(err)
            raise ConfigEntryAuthFailed from err
        except SentrymoEntitlementUnavailable as err:
            return self._entitlement_unavailable_snapshot(err)
        except SentrymoApiError as err:
            self._clear_entitlement_issue()
            self._apply_server_backoff(err)
            self._discard_if_access_denied(err)
            raise UpdateFailed(self._update_error_message(err)) from err

        self._clear_entitlement_issue()
        self.update_interval = self._parse_update_interval(snapshot)
        return snapshot

    def _entitlement_unavailable_snapshot(
        self, err: SentrymoEntitlementUnavailable
    ) -> dict[str, Any]:
        """Keep the entry loaded while making all old entities unavailable."""
        self.client.clear_segment_cache()
        snapshot = self._discard_current_snapshot(err)
        self.update_interval = _ENTITLEMENT_RECHECK_INTERVAL
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"entitlement_unavailable_{self.instance_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="entitlement_unavailable",
        )
        _LOGGER.warning("%s", self._update_error_message(err))
        return snapshot

    def _clear_entitlement_issue(self) -> None:
        """Clear the repair issue after authorized access recovers."""
        ir.async_delete_issue(
            self.hass,
            DOMAIN,
            f"entitlement_unavailable_{self.instance_id}",
        )

    def _disable_command_entities(self) -> None:
        """Disable command controls while preserving every read entity."""
        if not isinstance(self.data, dict):
            return

        snapshot = dict(self.data)
        capabilities = snapshot.get("capabilities", {})
        snapshot_capabilities = (
            dict(capabilities)
            if isinstance(capabilities, dict)
            else {}
        )
        snapshot_capabilities["commands"] = False
        snapshot_capabilities["commands_enabled"] = False
        snapshot["capabilities"] = snapshot_capabilities

        vehicles = snapshot.get("vehicles", [])
        if isinstance(vehicles, list):
            updated_vehicles = []
            for vehicle in vehicles:
                if not isinstance(vehicle, dict):
                    updated_vehicles.append(vehicle)
                    continue
                updated_vehicle = dict(vehicle)
                vehicle_capabilities = vehicle.get("capabilities", {})
                updated_capabilities = (
                    dict(vehicle_capabilities)
                    if isinstance(vehicle_capabilities, dict)
                    else {}
                )
                for key in (
                    "commands",
                    "commands_enabled",
                    "protection_commands",
                ):
                    updated_capabilities[key] = False
                updated_vehicle["capabilities"] = updated_capabilities
                updated_vehicles.append(updated_vehicle)
            snapshot["vehicles"] = updated_vehicles

        self.async_set_updated_data(snapshot)

    def _discard_vehicle(
        self, vehicle_id: str | int | None
    ) -> None:
        """Make a command-target vehicle unavailable until the next ACL read."""
        if vehicle_id is None or not isinstance(self.data, dict):
            return
        target = str(vehicle_id)
        vehicles = self.data.get("vehicles", [])
        if not isinstance(vehicles, list):
            return
        snapshot = dict(self.data)
        snapshot["vehicles"] = [
            vehicle
            for vehicle in vehicles
            if not isinstance(vehicle, dict)
            or str(vehicle.get("vehicle_id")) != target
        ]
        self.async_set_updated_data(snapshot)

    def _apply_server_backoff(self, err: SentrymoApiError) -> None:
        """Honor a numeric server Retry-After for coordinator requests."""
        if (
            isinstance(err, SentrymoRateLimited)
            and err.retry_after is not None
        ):
            self.update_interval = timedelta(seconds=err.retry_after)

    def _discard_if_access_denied(self, err: SentrymoApiError) -> None:
        """Discard data when a failure changes authorization semantics."""
        if not err.cache_allowed:
            self.client.clear_segment_cache()
            self._discard_current_snapshot(err)

    def _discard_current_snapshot(
        self, err: SentrymoApiError
    ) -> dict[str, Any]:
        """Keep registry objects but remove stale authorized vehicle data."""
        snapshot = {
            "vehicles": [],
            "segment_status": {},
            "access_status": {
                "code": err.code,
                "category": err.category.value,
            },
        }
        self.data = snapshot
        return snapshot

    def _update_error_message(self, err: SentrymoApiError) -> str:
        """Return an explanatory, non-secret coordinator error."""
        if isinstance(err, SentrymoEntitlementUnavailable):
            return (
                "The Sentrymo Home Assistant feature is not available in the "
                "current package. Existing entities are unavailable."
            )
        if err.code == "permission_denied":
            return (
                "Sentrymo denied access to this integration or operation. "
                "Existing entities are unavailable."
            )
        return str(err)

    def _parse_update_interval(
        self, snapshot: dict[str, Any]
    ) -> timedelta:
        """Resolve polling interval from snapshot data."""
        polling = snapshot.get("polling", {})
        seconds = None
        if isinstance(polling, dict):
            fast = polling.get("fast")
            if isinstance(fast, int) and fast > 0:
                seconds = fast

        if seconds is None:
            return DEFAULT_POLL_INTERVAL

        return timedelta(
            seconds=max(
                int(MIN_POLL_INTERVAL.total_seconds()),
                seconds,
            )
        )
