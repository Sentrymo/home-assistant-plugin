"""Constants for the Sentrymo integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "sentrymo"

CONF_API_URL = "api_url"
CONF_API_ENVIRONMENT = "api_environment"
CONF_SETUP_KEY = "setup_key"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_CPIN = "cpin"
CONF_TOKEN_EXPIRES_AT = "access_token_expires_at"

API_ENVIRONMENT_PRODUCTION = "production"
API_ENVIRONMENT_BETA = "beta"

DEFAULT_PROD_API_URL = "https://ha-api.sentrymo.eu/api/v1"
DEFAULT_QA_API_URL = "https://ha-api.qa.sentrymo.eu/api/v1"

DEFAULT_API_ENVIRONMENT = API_ENVIRONMENT_PRODUCTION

API_ENVIRONMENT_URLS = {
    API_ENVIRONMENT_PRODUCTION: DEFAULT_PROD_API_URL,
    API_ENVIRONMENT_BETA: DEFAULT_QA_API_URL,
}

DEFAULT_POLL_INTERVAL = timedelta(seconds=60)
MIN_POLL_INTERVAL = timedelta(seconds=30)
# How long last known values stay current during temporary network/server
# failures. Short outages must not flip entities to unavailable and back,
# because that transition fires state-based automations.
STALE_DATA_GRACE_PERIOD = timedelta(minutes=10)

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"
DATA_SERVICES_REGISTERED = "services_registered"

ATTR_ENTRY_ID = "entry_id"
ATTR_VEHICLE_ID = "vehicle_id"
ATTR_MODE = "mode"
ATTR_ENABLED = "enabled"

SERVICE_REFRESH = "refresh"
SERVICE_SET_PROTECTION_MODE = "set_protection_mode"
SERVICE_SET_IMMOBILIZER = "set_immobilizer"
SERVICE_SET_ACCESSORY = "set_accessory"

COMMAND_PROTECTION_ACTIVATE = "protection_activate"
COMMAND_PROTECTION_DEACTIVATE = "protection_deactivate"
COMMAND_PROTECTION_AUTO = "protection_auto"
COMMAND_IMMOBILIZER_ACTIVATE = "immobilizer_activate"
COMMAND_IMMOBILIZER_DEACTIVATE = "immobilizer_deactivate"
COMMAND_ACCESSORY_ACTIVATE = "accessory_activate"
COMMAND_ACCESSORY_DEACTIVATE = "accessory_deactivate"

PROTECTION_MODE_DISABLED = "disabled"
PROTECTION_MODE_MANUAL = "manual"
PROTECTION_MODE_AUTOMATIC = "automatic"
PROTECTION_MODE_OPTIONS = [
    PROTECTION_MODE_DISABLED,
    PROTECTION_MODE_MANUAL,
    PROTECTION_MODE_AUTOMATIC,
]

API_AUTH_EXCHANGE = "/auth/exchange"
API_AUTH_REFRESH = "/auth/refresh"
API_PROFILE = "/profile"
API_VEHICLES = "/vehicles"
API_STATE_FAST = "/state/fast"
API_STATE_TELEMETRY = "/state/telemetry"
API_STATE_SLOW = "/state/slow"
API_STATE_CONFIG = "/state/config"

DEFAULT_EXCHANGE_PAYLOAD: dict[str, int] = {
    "fast": 60,
    "telemetry": 60,
    "slow": 300,
    "config": 3600,
}

DEFAULT_ENTRY_TITLE = "Sentrymo"
DEFAULT_CLIENT_NAME = "Home Assistant"
DEFAULT_SOURCE = "home_assistant"

PLATFORMS = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
]
