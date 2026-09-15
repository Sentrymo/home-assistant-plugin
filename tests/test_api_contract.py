"""Contract, authorization, cache and command tests without a full HA install."""

from __future__ import annotations

import datetime as datetime_module
from datetime import datetime, timedelta, timezone
from enum import Enum
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from typing import Any

import yaml


ROOT = Path(__file__).parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "sentrymo"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_dependency_stubs() -> None:
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    sys.modules.setdefault("custom_components", custom_components)

    package = types.ModuleType("custom_components.sentrymo")
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules.setdefault("custom_components.sentrymo", package)

    async_timeout = types.ModuleType("async_timeout")

    class _Timeout:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async_timeout.timeout = lambda seconds: _Timeout()
    sys.modules["async_timeout"] = async_timeout

    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    aiohttp.ClientError = ClientError
    aiohttp.ClientResponse = object
    aiohttp.ClientSession = object
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    sys.modules["homeassistant"] = homeassistant

    ha_const = types.ModuleType("homeassistant.const")

    class Platform(str, Enum):
        DEVICE_TRACKER = "device_tracker"
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"
        SELECT = "select"
        SWITCH = "switch"
        BUTTON = "button"

    ha_const.Platform = Platform
    sys.modules["homeassistant.const"] = ha_const

    ha_util = types.ModuleType("homeassistant.util")
    dt_util = types.ModuleType("homeassistant.util.dt")

    def utcnow() -> datetime:
        return datetime.now(UTC)

    def parse_datetime(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    dt_util.utcnow = utcnow
    dt_util.parse_datetime = parse_datetime
    ha_util.dt = dt_util
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.dt"] = dt_util

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    diagnostics = types.ModuleType("homeassistant.components.diagnostics")

    def async_redact_data(data, keys):
        if isinstance(data, dict):
            return {
                key: "**REDACTED**"
                if key in keys
                else async_redact_data(value, keys)
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [async_redact_data(item, keys) for item in data]
        return data

    diagnostics.async_redact_data = async_redact_data
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.diagnostics"] = diagnostics

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntryAuthFailed(Exception):
        pass

    config_entries.ConfigEntry = object
    config_entries.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    sys.modules["homeassistant.config_entries"] = config_entries

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    issue_registry = types.ModuleType(
        "homeassistant.helpers.issue_registry"
    )
    issue_registry.created = []
    issue_registry.deleted = []

    class IssueSeverity(str, Enum):
        ERROR = "error"

    def async_create_issue(hass, domain, issue_id, **kwargs):
        issue_registry.created.append(
            (hass, domain, issue_id, kwargs)
        )

    def async_delete_issue(hass, domain, issue_id):
        issue_registry.deleted.append((hass, domain, issue_id))

    issue_registry.IssueSeverity = IssueSeverity
    issue_registry.async_create_issue = async_create_issue
    issue_registry.async_delete_issue = async_delete_issue
    helpers.issue_registry = issue_registry
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules[
        "homeassistant.helpers.issue_registry"
    ] = issue_registry

    update_coordinator = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, item):
            del item
            return cls

        def __init__(
            self,
            hass,
            logger,
            *,
            name,
            update_interval,
        ):
            del logger, name
            self.hass = hass
            self.data = None
            self.last_update_success = False
            self.update_interval = update_interval

        def async_set_updated_data(self, data):
            self.data = data
            self.last_update_success = True

    class CoordinatorEntity:
        @classmethod
        def __class_getitem__(cls, item):
            del item
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    update_coordinator.UpdateFailed = UpdateFailed
    sys.modules[
        "homeassistant.helpers.update_coordinator"
    ] = update_coordinator

    device_registry = types.ModuleType(
        "homeassistant.helpers.device_registry"
    )
    device_registry.DeviceInfo = dict
    sys.modules[
        "homeassistant.helpers.device_registry"
    ] = device_registry

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.core"] = core


_install_dependency_stubs()
if not hasattr(datetime_module, "UTC"):
    datetime_module.UTC = timezone.utc
UTC = timezone.utc
_module(
    "custom_components.sentrymo.api_url",
    PACKAGE_DIR / "api_url.py",
)
const = _module(
    "custom_components.sentrymo.const",
    PACKAGE_DIR / "const.py",
)
errors = _module(
    "custom_components.sentrymo.errors",
    PACKAGE_DIR / "errors.py",
)
commands = _module(
    "custom_components.sentrymo.commands",
    PACKAGE_DIR / "commands.py",
)
api = _module(
    "custom_components.sentrymo.api",
    PACKAGE_DIR / "api.py",
)
coordinator_module = _module(
    "custom_components.sentrymo.coordinator",
    PACKAGE_DIR / "coordinator.py",
)
entity_module = _module(
    "custom_components.sentrymo.entity",
    PACKAGE_DIR / "entity.py",
)
diagnostics_module = _module(
    "custom_components.sentrymo.diagnostics",
    PACKAGE_DIR / "diagnostics.py",
)


class FakeResponse:
    """Small aiohttp response substitute."""

    def __init__(
        self,
        status: int,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}

    async def json(self, *, content_type=None):
        del content_type
        return self.body


class FakeSession:
    """Queue-backed aiohttp client substitute."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def request(self, method, url, *, json=None, headers=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "headers": headers,
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def ok(body: dict[str, Any]) -> FakeResponse:
    return FakeResponse(200, body)


def failure(
    status: int,
    code: str,
    message: str = "server message",
    *,
    headers: dict[str, str] | None = None,
) -> FakeResponse:
    return FakeResponse(
        status,
        {"code": code, "message": message},
        headers=headers,
    )


def profile() -> FakeResponse:
    return ok(
        {
            "polling": {
                "fast": 60,
                "telemetry": 60,
                "slow": 300,
                "config": 3600,
            },
            "account": {"name": "Account"},
            "capabilities": {"commands": True},
        }
    )


def vehicles(*vehicle_ids: int) -> FakeResponse:
    return ok(
        {
            "vehicles": [
                {
                    "vehicle_id": vehicle_id,
                    "name": f"Vehicle {vehicle_id}",
                    "capabilities": {"commands": True},
                }
                for vehicle_id in vehicle_ids
            ]
        }
    )


def segment(
    *vehicle_ids: int,
    state: dict[str, Any] | None = None,
) -> FakeResponse:
    return ok(
        {
            "recommended_poll_seconds": 60,
            "vehicles": [
                {
                    "vehicle_id": vehicle_id,
                    "state": dict(state or {}),
                }
                for vehicle_id in vehicle_ids
            ],
        }
    )


def successful_snapshot_responses(*vehicle_ids: int) -> list[FakeResponse]:
    return [
        profile(),
        vehicles(*vehicle_ids),
        segment(*vehicle_ids, state={"online": True}),
        segment(*vehicle_ids, state={"speed_kmh": 25}),
        segment(*vehicle_ids, state={"odometer_km": 100}),
        segment(*vehicle_ids),
    ]


def client(
    responses: list[Any],
    *,
    cpin: str | None = None,
    callback=None,
):
    return api.SentrymoApiClient(
        FakeSession(responses),
        access_token="access",
        refresh_token="refresh",
        cpin=cpin,
        token_update_callback=callback,
    )


class ErrorContractTest(unittest.TestCase):
    """Verify the complete stable error contract."""

    def test_all_server_codes_have_explicit_behaviour(self) -> None:
        expected = {
            "missing_token",
            "invalid_token",
            "token_expired",
            "invalid_setup_key",
            "setup_key_expired",
            "invalid_refresh_token",
            "refresh_token_expired",
            "integration_revoked",
            "invalid_authentication",
            "home_assistant_feature_unavailable",
            "permission_denied",
            "commands_disabled",
            "vehicle_unavailable",
            "unsupported_command",
            "not_found",
            "method_not_allowed",
            "validation_error",
            "missing_cpin",
            "invalid_cpin",
            "output_not_configured",
            "command_failed",
            "cpin_locked",
            "rate_limited",
            "internal_error",
            "not_ready",
        }
        self.assertEqual(set(errors.ERROR_BEHAVIORS), expected)

    def test_only_authentication_codes_require_reauth(self) -> None:
        non_auth = {
            "home_assistant_feature_unavailable",
            "permission_denied",
            "commands_disabled",
            "vehicle_unavailable",
            "unsupported_command",
            "missing_cpin",
            "invalid_cpin",
            "cpin_locked",
            "rate_limited",
            "internal_error",
            "not_ready",
        }
        for code in non_auth:
            with self.subTest(code=code):
                self.assertFalse(
                    errors.behavior_for_error(code).reauth_required
                )

        for code in {
            "invalid_authentication",
            "integration_revoked",
            "invalid_refresh_token",
            "refresh_token_expired",
        }:
            with self.subTest(code=code):
                self.assertTrue(
                    errors.behavior_for_error(code).reauth_required
                )


class AuthenticationTest(unittest.IsolatedAsyncioTestCase):
    """Verify token refresh and reauthentication boundaries."""

    async def test_valid_token_is_sent(self) -> None:
        instance = client([profile()])
        result = await instance.async_get_profile()
        self.assertEqual(result["account"]["name"], "Account")
        request = instance._session.requests[0]
        self.assertEqual(
            request["headers"]["Authorization"],
            "Bearer access",
        )

    async def test_missing_token_does_not_attempt_refresh(
        self,
    ) -> None:
        instance = client([failure(401, "missing_token")])
        with self.assertRaises(errors.SentrymoInvalidAuth):
            await instance.async_get_profile()
        self.assertEqual(len(instance._session.requests), 1)

    async def test_invalid_authentication_requires_reauth_without_refresh(
        self,
    ) -> None:
        instance = client(
            [failure(401, "invalid_authentication")]
        )
        with self.assertRaises(errors.SentrymoInvalidAuth) as raised:
            await instance.async_get_profile()
        self.assertTrue(raised.exception.reauth_required)
        self.assertFalse(raised.exception.invalidate_session)
        self.assertEqual(len(instance._session.requests), 1)

    async def test_revocation_invalidates_session_and_cache(self) -> None:
        updates: list[dict[str, str | None]] = []

        async def callback(values):
            updates.append(values)

        instance = client(
            [failure(401, "integration_revoked")],
            callback=callback,
        )
        instance._segment_cache["fast"] = {"vehicles": []}

        with self.assertRaises(
            errors.SentrymoIntegrationRevoked
        ) as raised:
            await instance.async_get_profile()

        self.assertTrue(raised.exception.reauth_required)
        self.assertIsNone(instance.access_token)
        self.assertIsNone(instance.refresh_token)
        self.assertEqual(instance._segment_cache, {})
        self.assertEqual(
            updates[-1],
            {
                const.CONF_ACCESS_TOKEN: None,
                const.CONF_REFRESH_TOKEN: None,
                const.CONF_TOKEN_EXPIRES_AT: None,
            },
        )
        self.assertEqual(len(instance._session.requests), 1)

    async def test_refresh_token_failure_is_not_hidden(self) -> None:
        instance = client(
            [
                failure(401, "token_expired"),
                failure(401, "invalid_refresh_token"),
            ]
        )
        with self.assertRaises(errors.SentrymoInvalidAuth) as raised:
            await instance.async_get_profile()

        self.assertEqual(
            raised.exception.code,
            "invalid_refresh_token",
        )
        self.assertTrue(raised.exception.reauth_required)
        self.assertEqual(len(instance._session.requests), 2)


class EntitlementAndAclTest(unittest.IsolatedAsyncioTestCase):
    """Verify entitlement loss and authoritative vehicle filtering."""

    async def test_entitlement_loss_never_uses_segment_cache(self) -> None:
        instance = client(
            [
                failure(
                    403,
                    "home_assistant_feature_unavailable",
                )
            ]
        )
        instance._segment_cache["fast"] = {
            "vehicles": [
                {"vehicle_id": 1, "state": {"online": True}}
            ]
        }

        with self.assertRaises(
            errors.SentrymoEntitlementUnavailable
        ) as raised:
            await instance.async_get_snapshot()

        self.assertFalse(raised.exception.reauth_required)
        self.assertFalse(raised.exception.cache_allowed)
        self.assertEqual(instance._segment_cache, {})

    async def test_segment_entitlement_loss_clears_all_cache(self) -> None:
        instance = client(
            [
                profile(),
                vehicles(1),
                failure(
                    403,
                    "home_assistant_feature_unavailable",
                ),
            ]
        )
        instance._segment_cache["slow"] = {
            "vehicles": [{"vehicle_id": 1}]
        }

        with self.assertRaises(
            errors.SentrymoEntitlementUnavailable
        ):
            await instance.async_get_snapshot()

        self.assertEqual(instance._segment_cache, {})

    async def test_state_segment_cannot_create_removed_vehicle(self) -> None:
        instance = client(
            [
                profile(),
                vehicles(2),
                segment(1, 2, state={"online": True}),
                segment(1, 2, state={"speed_kmh": 42}),
                segment(1, 2, state={"odometer_km": 12}),
                segment(1, 2),
            ]
        )
        snapshot = await instance.async_get_snapshot()
        self.assertEqual(
            [item["vehicle_id"] for item in snapshot["vehicles"]],
            ["2"],
        )

    async def test_cached_segment_cannot_revive_old_vehicle(self) -> None:
        instance = client(
            [
                profile(),
                vehicles(2),
                segment(2),
                segment(2),
                segment(2),
            ]
        )
        instance._segment_cache["fast"] = {
            "vehicles": [
                {"vehicle_id": 1, "state": {"online": True}},
                {"vehicle_id": 2, "state": {"online": True}},
            ]
        }
        instance._segment_next_refresh["fast"] = (
            datetime.now(UTC) + timedelta(minutes=5)
        )

        snapshot = await instance.async_get_snapshot()
        self.assertEqual(
            [item["vehicle_id"] for item in snapshot["vehicles"]],
            ["2"],
        )
        self.assertEqual(
            [
                item["vehicle_id"]
                for item in instance._segment_cache["fast"]["vehicles"]
            ],
            [2],
        )

    async def test_allowlist_reduction_prunes_existing_cache(self) -> None:
        instance = client(successful_snapshot_responses(1, 2))
        first = await instance.async_get_snapshot()
        self.assertEqual(len(first["vehicles"]), 2)

        instance._session.responses.extend([profile(), vehicles(2)])
        second = await instance.async_get_snapshot()
        self.assertEqual(
            [item["vehicle_id"] for item in second["vehicles"]],
            ["2"],
        )
        for response in instance._segment_cache.values():
            self.assertEqual(
                {
                    str(item["vehicle_id"])
                    for item in response["vehicles"]
                },
                {"2"},
            )

    async def test_vehicle_unavailable_is_not_authentication(self) -> None:
        instance = client(
            [failure(404, "vehicle_unavailable")]
        )
        with self.assertRaises(
            errors.SentrymoVehicleUnavailable
        ) as raised:
            await instance.async_send_command(
                99, "protection_activate"
            )
        self.assertFalse(raised.exception.reauth_required)
        self.assertFalse(raised.exception.cache_allowed)

    async def test_permission_denied_is_not_authentication(self) -> None:
        instance = client([failure(403, "permission_denied")])
        with self.assertRaises(
            errors.SentrymoAuthorizationError
        ) as raised:
            await instance.async_get_vehicles()
        self.assertFalse(raised.exception.reauth_required)


class ScopeTest(unittest.IsolatedAsyncioTestCase):
    """Verify read and command scope isolation."""

    async def test_missing_read_scope_only_marks_its_segment(self) -> None:
        instance = client(
            [
                profile(),
                vehicles(1),
                failure(403, "permission_denied"),
                segment(1, state={"speed_kmh": 30}),
                segment(1, state={"odometer_km": 10}),
                segment(1),
            ]
        )
        instance._segment_cache["fast"] = {
            "vehicles": [
                {"vehicle_id": 1, "state": {"online": True}}
            ]
        }

        snapshot = await instance.async_get_snapshot()
        vehicle = snapshot["vehicles"][0]
        self.assertEqual(
            snapshot["segment_status"]["fast"],
            "unavailable",
        )
        self.assertIn("fast", vehicle["_unavailable_segments"])
        self.assertNotIn("online", vehicle.get("state", {}))
        self.assertNotIn("fast", instance._segment_cache)

    async def test_command_scope_denial_does_not_break_reads(self) -> None:
        instance = client(
            [
                failure(403, "permission_denied"),
                *successful_snapshot_responses(1),
            ],
            cpin="1234",
        )
        with self.assertRaises(
            errors.SentrymoCapabilityError
        ) as raised:
            await instance.async_set_protection_mode(1, "manual")
        self.assertFalse(raised.exception.reauth_required)

        snapshot = await instance.async_get_snapshot()
        self.assertEqual(snapshot["vehicles"][0]["vehicle_id"], "1")
        self.assertTrue(
            snapshot["vehicles"][0]["state"]["online"]
        )


class TemporaryFailureTest(unittest.IsolatedAsyncioTestCase):
    """Verify bounded fallback for rate limits and outages."""

    async def _snapshot_with_fast_failure(
        self, response: FakeResponse
    ) -> tuple[Any, dict[str, Any]]:
        instance = client(
            [
                profile(),
                vehicles(1),
                response,
                segment(1, state={"speed_kmh": 5}),
                segment(1),
                segment(1),
            ]
        )
        instance._segment_cache["fast"] = {
            "vehicles": [
                {"vehicle_id": 1, "state": {"online": True}}
            ]
        }
        instance._segment_next_refresh["fast"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        )
        return instance, await instance.async_get_snapshot()

    async def test_rate_limit_uses_cache_as_non_current(self) -> None:
        instance, snapshot = await self._snapshot_with_fast_failure(
            failure(
                429,
                "rate_limited",
                headers={"Retry-After": "300"},
            )
        )
        vehicle = snapshot["vehicles"][0]
        self.assertTrue(vehicle["state"]["online"])
        self.assertIn("fast", vehicle["_unavailable_segments"])
        self.assertEqual(
            snapshot["segment_status"]["fast"],
            "cached",
        )
        self.assertFalse(
            errors.behavior_for_error(
                "rate_limited"
            ).reauth_required
        )
        self.assertEqual(len(instance._session.requests), 6)
        self.assertGreater(
            instance._segment_next_refresh["fast"],
            datetime.now(UTC) + timedelta(minutes=4),
        )

        instance._session.responses.extend([profile(), vehicles(1)])
        next_snapshot = await instance.async_get_snapshot()
        self.assertEqual(
            next_snapshot["segment_status"]["fast"],
            "cached",
        )
        self.assertIn(
            "fast",
            next_snapshot["vehicles"][0]["_unavailable_segments"],
        )

        request_count = len(instance._session.requests)
        await instance._get_segment(
            "fast", const.API_STATE_FAST, force=True
        )
        self.assertEqual(
            len(instance._session.requests), request_count
        )

    async def test_temporary_5xx_uses_cache_as_non_current(self) -> None:
        _, snapshot = await self._snapshot_with_fast_failure(
            failure(503, "not_ready")
        )
        self.assertTrue(
            snapshot["vehicles"][0]["state"]["online"]
        )
        self.assertIn(
            "fast",
            snapshot["vehicles"][0]["_unavailable_segments"],
        )

    async def test_timeout_is_retryable_without_reauth(self) -> None:
        instance = client([TimeoutError()])
        with self.assertRaises(
            errors.SentrymoCannotConnect
        ) as raised:
            await instance.async_get_profile()
        self.assertTrue(raised.exception.cache_allowed)
        self.assertTrue(raised.exception.retryable)
        self.assertFalse(raised.exception.reauth_required)


class CoordinatorBehaviourTest(unittest.IsolatedAsyncioTestCase):
    """Verify config-entry state for entitlement and authentication."""

    async def test_entitlement_keeps_entry_loaded_and_unavailable(
        self,
    ) -> None:
        entitlement_error = errors.exception_for_error(
            code="home_assistant_feature_unavailable",
            message="feature unavailable",
            status=403,
            path="/profile",
        )

        class BlockedClient:
            cache_cleared = False

            async def async_get_snapshot(self):
                raise entitlement_error

            def clear_segment_cache(self):
                self.cache_cleared = True

        class ConfigEntries:
            def async_get_entry(self, entry_id):
                del entry_id
                return None

        class Hass:
            config_entries = ConfigEntries()

        blocked_client = BlockedClient()
        coordinator = coordinator_module.SentrymoDataUpdateCoordinator(
            Hass(), blocked_client, "entry"
        )
        snapshot = await coordinator._async_update_data()

        self.assertEqual(snapshot["vehicles"], [])
        self.assertEqual(
            snapshot["access_status"]["code"],
            "home_assistant_feature_unavailable",
        )
        self.assertTrue(blocked_client.cache_cleared)
        self.assertEqual(
            coordinator.update_interval,
            timedelta(hours=1),
        )
        issue_registry = sys.modules[
            "homeassistant.helpers.issue_registry"
        ]
        self.assertTrue(issue_registry.created)
        self.assertEqual(
            issue_registry.created[-1][2],
            "entitlement_unavailable_entry",
        )

    async def test_invalid_authentication_raises_standard_reauth(
        self,
    ) -> None:
        auth_error = errors.exception_for_error(
            code="invalid_authentication",
            message="invalid authentication",
            status=401,
            path="/profile",
        )

        class InvalidClient:
            async def async_get_snapshot(self):
                raise auth_error

            def clear_segment_cache(self):
                pass

        class ConfigEntries:
            def async_get_entry(self, entry_id):
                del entry_id
                return None

        class Hass:
            config_entries = ConfigEntries()

        coordinator = coordinator_module.SentrymoDataUpdateCoordinator(
            Hass(), InvalidClient(), "entry"
        )
        config_entries = sys.modules["homeassistant.config_entries"]
        with self.assertRaises(
            config_entries.ConfigEntryAuthFailed
        ):
            await coordinator._async_update_data()
        self.assertEqual(coordinator.vehicles, [])


    async def test_command_scope_denial_disables_only_commands(
        self,
    ) -> None:
        permission_error = errors.exception_for_error(
            code="permission_denied",
            message="scope unavailable",
            status=403,
            path="/vehicles/1/commands/protection_activate",
        )

        class Client:
            def clear_segment_cache(self):
                raise AssertionError("read cache must remain intact")

        class ConfigEntries:
            def async_get_entry(self, entry_id):
                del entry_id
                return None

        class Hass:
            config_entries = ConfigEntries()

        coordinator = coordinator_module.SentrymoDataUpdateCoordinator(
            Hass(), Client(), "entry"
        )
        coordinator.data = {
            "vehicles": [
                {
                    "vehicle_id": "1",
                    "state": {"online": True},
                    "capabilities": {
                        "commands": True,
                        "commands_enabled": True,
                    },
                }
            ]
        }
        coordinator.async_handle_command_error(
            permission_error, vehicle_id="1"
        )
        self.assertEqual(len(coordinator.vehicles), 1)
        self.assertTrue(
            coordinator.vehicles[0]["state"]["online"]
        )
        self.assertFalse(
            coordinator.vehicles[0]["capabilities"]["commands"]
        )

    async def test_command_entitlement_invalidates_read_snapshot(
        self,
    ) -> None:
        entitlement_error = errors.exception_for_error(
            code="home_assistant_feature_unavailable",
            message="feature unavailable",
            status=403,
            path="/vehicles/1/commands/protection_activate",
        )

        class Client:
            cache_cleared = False

            def clear_segment_cache(self):
                self.cache_cleared = True

        class ConfigEntries:
            def async_get_entry(self, entry_id):
                del entry_id
                return None

        class Hass:
            config_entries = ConfigEntries()

        command_client = Client()
        coordinator = coordinator_module.SentrymoDataUpdateCoordinator(
            Hass(), command_client, "entry"
        )
        coordinator.data = {
            "vehicles": [{"vehicle_id": "1"}]
        }
        coordinator.async_handle_command_error(
            entitlement_error, vehicle_id="1"
        )
        self.assertEqual(coordinator.vehicles, [])
        self.assertTrue(command_client.cache_cleared)

    async def test_command_vehicle_unavailable_removes_only_target(
        self,
    ) -> None:
        vehicle_error = errors.exception_for_error(
            code="vehicle_unavailable",
            message="vehicle unavailable",
            status=404,
            path="/vehicles/1/commands/protection_activate",
        )

        class Client:
            def clear_segment_cache(self):
                pass

        class ConfigEntries:
            def async_get_entry(self, entry_id):
                del entry_id
                return None

        class Hass:
            config_entries = ConfigEntries()

        coordinator = coordinator_module.SentrymoDataUpdateCoordinator(
            Hass(), Client(), "entry"
        )
        coordinator.data = {
            "vehicles": [
                {"vehicle_id": "1"},
                {"vehicle_id": "2"},
            ]
        }
        coordinator.async_handle_command_error(
            vehicle_error, vehicle_id="1"
        )
        self.assertEqual(
            [item["vehicle_id"] for item in coordinator.vehicles],
            ["2"],
        )


class EntityAvailabilityTest(unittest.TestCase):
    """Verify non-destructive entity behaviour after ACL changes."""

    def test_removed_vehicle_entity_remains_but_is_unavailable(
        self,
    ) -> None:
        class Coordinator:
            last_update_success = True
            instance_id = "entry"

            def vehicle_by_id(self, vehicle_id):
                del vehicle_id
                return None

        entity = entity_module.SentrymoEntity(
            Coordinator(), "1", "speed"
        )
        self.assertFalse(entity.available)

    def test_denied_segment_only_disables_dependent_entities(
        self,
    ) -> None:
        vehicle = {
            "vehicle_id": "1",
            "_unavailable_segments": ["fast"],
        }

        class Coordinator:
            last_update_success = True
            instance_id = "entry"

            def vehicle_by_id(self, vehicle_id):
                del vehicle_id
                return vehicle

        coordinator = Coordinator()
        fast_entity = entity_module.SentrymoEntity(
            coordinator, "1", "moving"
        )
        telemetry_entity = entity_module.SentrymoEntity(
            coordinator, "1", "speed"
        )
        self.assertFalse(fast_entity.available)
        self.assertTrue(telemetry_entity.available)


class CommandAndCpinTest(unittest.IsolatedAsyncioTestCase):
    """Verify acknowledgement semantics and CPIN handling."""

    def test_only_supported_acknowledgements_change_local_state(self) -> None:
        self.assertTrue(
            commands.protection_update_was_accepted(
                {"ok": True, "status": "accepted"}
            )
        )
        self.assertFalse(
            commands.protection_update_was_accepted(
                {"ok": True, "status": "queued"}
            )
        )
        self.assertFalse(
            commands.output_update_was_confirmed(
                {"ok": True, "status": "queued"}
            )
        )
        self.assertTrue(
            commands.output_update_was_confirmed(
                {"ok": True, "status": "confirmed"}
            )
        )

    async def test_cpin_error_is_redacted_and_does_not_reauth(self) -> None:
        secret = "9876"
        instance = client(
            [
                failure(
                    422,
                    "invalid_cpin",
                    f"bad CPIN {secret}",
                )
            ],
            cpin=secret,
        )

        with self.assertRaises(
            errors.SentrymoCommandError
        ) as raised:
            await instance.async_set_immobilizer_active(1, True)

        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, repr(raised.exception))
        self.assertFalse(raised.exception.reauth_required)
        request = instance._session.requests[0]
        self.assertNotIn("cpin", repr(request["json"]).lower())
        self.assertEqual(
            commands.command_error_translation_key(
                raised.exception
            ),
            "command_invalid_cpin",
        )

    async def test_command_without_cpin_has_localized_error_key(
        self,
    ) -> None:
        instance = client([failure(422, "missing_cpin")])
        with self.assertRaises(
            errors.SentrymoCommandError
        ) as raised:
            await instance.async_set_accessory_active(1, True)
        self.assertEqual(
            commands.command_error_translation_key(
                raised.exception
            ),
            "command_missing_cpin",
        )
        self.assertFalse(raised.exception.reauth_required)

    async def test_diagnostics_redact_every_credential(self) -> None:
        secret_values = {
            const.CONF_ACCESS_TOKEN: "access-secret",
            const.CONF_REFRESH_TOKEN: "refresh-secret",
            const.CONF_TOKEN_EXPIRES_AT: "expiry-secret",
            const.CONF_SETUP_KEY: "setup-secret",
            const.CONF_CPIN: "2468",
            const.CONF_API_URL: "https://ha-api.sentrymo.eu/api/v1",
        }

        class Entry:
            entry_id = "entry"
            data = secret_values
            options = {const.CONF_CPIN: "1357"}

        class Coordinator:
            data = {
                "segment_status": {"fast": "fresh"},
                "access_status": {},
            }
            last_update_success = True
            vehicles = [{"vehicle_id": "1"}]

        class Hass:
            data = {
                const.DOMAIN: {
                    "entry": {
                        const.DATA_COORDINATOR: Coordinator()
                    }
                }
            }

        result = (
            await diagnostics_module.async_get_config_entry_diagnostics(
                Hass(), Entry()
            )
        )
        serialized = repr(result)
        for value in (
            "access-secret",
            "refresh-secret",
            "expiry-secret",
            "setup-secret",
            "2468",
            "1357",
        ):
            self.assertNotIn(value, serialized)
        self.assertIn("**REDACTED**", serialized)


class ResourceValidationTest(unittest.TestCase):
    """Validate Home Assistant metadata and localized resource parity."""

    def test_manifest_and_hacs_metadata_are_valid(self) -> None:
        manifest = json.loads(
            (PACKAGE_DIR / "manifest.json").read_text()
        )
        hacs = json.loads((ROOT / "hacs.json").read_text())
        self.assertEqual(manifest["domain"], "sentrymo")
        self.assertEqual(manifest["config_flow"], True)
        self.assertEqual(hacs["domains"], ["sentrymo"])

    def test_services_yaml_is_valid(self) -> None:
        services = yaml.safe_load(
            (PACKAGE_DIR / "services.yaml").read_text()
        )
        self.assertEqual(
            set(services),
            {
                "refresh",
                "set_protection_mode",
                "set_immobilizer",
                "set_accessory",
            },
        )

    def test_en_sk_cs_have_matching_error_and_issue_keys(
        self,
    ) -> None:
        base = json.loads(
            (PACKAGE_DIR / "strings.json").read_text()
        )
        expected_exceptions = set(base["exceptions"])
        expected_issues = set(base["issues"])
        expected_errors = set(base["config"]["error"])

        for language in ("en", "sk", "cs"):
            with self.subTest(language=language):
                translated = json.loads(
                    (
                        PACKAGE_DIR
                        / "translations"
                        / f"{language}.json"
                    ).read_text()
                )
                self.assertEqual(
                    set(translated["exceptions"]),
                    expected_exceptions,
                )
                self.assertEqual(
                    set(translated["issues"]),
                    expected_issues,
                )
                self.assertEqual(
                    set(translated["config"]["error"]),
                    expected_errors,
                )


if __name__ == "__main__":
    unittest.main()
