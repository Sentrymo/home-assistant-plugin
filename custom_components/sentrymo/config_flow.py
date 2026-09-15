"""Config flow for Sentrymo."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import SentrymoApiClient
from .const import (
    API_ENVIRONMENT_BETA,
    API_ENVIRONMENT_PRODUCTION,
    API_ENVIRONMENT_URLS,
    CONF_ACCESS_TOKEN,
    CONF_API_ENVIRONMENT,
    CONF_API_URL,
    CONF_CPIN,
    CONF_REFRESH_TOKEN,
    CONF_SETUP_KEY,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_API_ENVIRONMENT,
    DOMAIN,
)
from .errors import (
    SentrymoCannotConnect,
    SentrymoEntitlementUnavailable,
    SentrymoInvalidAuth,
)

API_ENVIRONMENT_OPTIONS = [
    API_ENVIRONMENT_PRODUCTION,
    API_ENVIRONMENT_BETA,
]


def _api_environment_selector() -> SelectSelector:
    """Return the API environment selector."""
    return SelectSelector(
        SelectSelectorConfig(
            options=API_ENVIRONMENT_OPTIONS,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_API_ENVIRONMENT,
        )
    )


def _resolve_api_url(api_environment: str) -> str:
    """Resolve the selected environment to an internal API URL."""
    return API_ENVIRONMENT_URLS.get(
        api_environment,
        API_ENVIRONMENT_URLS[DEFAULT_API_ENVIRONMENT],
    )


def _environment_from_api_url(api_url: str | None) -> str:
    """Infer the environment from a persisted API URL."""
    normalized_api_url = SentrymoApiClient.normalize_api_url(api_url)
    for environment, environment_url in API_ENVIRONMENT_URLS.items():
        if normalized_api_url == SentrymoApiClient.normalize_api_url(
            environment_url
        ):
            return environment
    return DEFAULT_API_ENVIRONMENT


def _validate_cpin(cpin: str) -> bool:
    """Return true for an empty or four-digit CPIN."""
    return not cpin or (cpin.isdigit() and len(cpin) == 4)


def _pairing_error(err: Exception) -> str:
    """Map pairing exceptions to config-flow error keys."""
    if isinstance(err, SentrymoEntitlementUnavailable):
        return "feature_unavailable"
    if isinstance(err, SentrymoCannotConnect):
        return "cannot_connect"
    if isinstance(err, SentrymoInvalidAuth):
        if err.code == "setup_key_expired":
            return "setup_key_expired"
        return "invalid_auth"
    return "unknown"


class SentrymoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sentrymo."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SentrymoOptionsFlow:
        """Create the options flow."""
        return SentrymoOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle initial pairing."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_url = _resolve_api_url(
                str(user_input[CONF_API_ENVIRONMENT])
            )
            normalized_api_url = SentrymoApiClient.normalize_api_url(
                api_url
            )
            await self.async_set_unique_id(normalized_api_url.lower())
            self._abort_if_unique_id_configured()

            cpin = str(user_input.get(CONF_CPIN) or "").strip()
            if not _validate_cpin(cpin):
                errors["base"] = "invalid_cpin"
            else:
                try:
                    client = SentrymoApiClient(
                        async_get_clientsession(self.hass)
                    )
                    await client.async_exchange_setup_key(
                        api_url,
                        str(user_input[CONF_SETUP_KEY]),
                        cpin,
                        client_name=str(
                            user_input.get(CONF_NAME) or "Sentrymo"
                        ),
                    )
                except (
                    SentrymoCannotConnect,
                    SentrymoEntitlementUnavailable,
                    SentrymoInvalidAuth,
                ) as err:
                    errors["base"] = _pairing_error(err)
                except Exception:
                    errors["base"] = "unknown"
                else:
                    data = {
                        CONF_NAME: user_input.get(CONF_NAME, "Sentrymo"),
                        CONF_API_URL: client.api_url,
                        CONF_ACCESS_TOKEN: client.access_token,
                        CONF_REFRESH_TOKEN: client.refresh_token,
                        CONF_TOKEN_EXPIRES_AT: client.token_expires_at,
                    }
                    if cpin:
                        # CPIN is required by command endpoints and is stored
                        # only in Home Assistant's config entry.
                        data[CONF_CPIN] = cpin

                    return self.async_create_entry(
                        title=str(
                            user_input.get(CONF_NAME) or "Sentrymo"
                        ),
                        data=data,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self._pairing_schema(),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ):
        """Start standard Home Assistant reauthentication."""
        del entry_data
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        """Exchange a new one-time key and replace the local session."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if user_input is not None:
            api_url = _resolve_api_url(
                str(user_input[CONF_API_ENVIRONMENT])
            )
            cpin = str(user_input.get(CONF_CPIN) or "").strip()
            if not _validate_cpin(cpin):
                errors["base"] = "invalid_cpin"
            else:
                try:
                    client = SentrymoApiClient(
                        async_get_clientsession(self.hass)
                    )
                    await client.async_exchange_setup_key(
                        api_url,
                        str(user_input[CONF_SETUP_KEY]),
                        cpin,
                        client_name=str(entry.title or "Sentrymo"),
                    )
                except (
                    SentrymoCannotConnect,
                    SentrymoEntitlementUnavailable,
                    SentrymoInvalidAuth,
                ) as err:
                    errors["base"] = _pairing_error(err)
                except Exception:
                    errors["base"] = "unknown"
                else:
                    data = dict(entry.data)
                    data.update(
                        {
                            CONF_API_URL: client.api_url,
                            CONF_ACCESS_TOKEN: client.access_token,
                            CONF_REFRESH_TOKEN: client.refresh_token,
                            CONF_TOKEN_EXPIRES_AT: (
                                client.token_expires_at
                            ),
                        }
                    )
                    if cpin:
                        data[CONF_CPIN] = cpin
                    else:
                        data.pop(CONF_CPIN, None)
                    data.pop(CONF_SETUP_KEY, None)
                    self.hass.config_entries.async_update_entry(
                        entry, data=data
                    )
                    return self.async_update_reload_and_abort(entry)

        current_api_url = entry.options.get(
            CONF_API_URL,
            entry.data.get(CONF_API_URL),
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self._pairing_schema(
                default_environment=_environment_from_api_url(
                    current_api_url
                ),
                include_name=False,
            ),
            errors=errors,
        )

    def _pairing_schema(
        self,
        *,
        default_environment: str = DEFAULT_API_ENVIRONMENT,
        include_name: bool = True,
    ) -> vol.Schema:
        """Return a pairing form without pre-filling secrets."""
        fields: dict[Any, Any] = {}
        if include_name:
            fields[vol.Required(CONF_NAME, default="Sentrymo")] = str
        fields[
            vol.Required(
                CONF_API_ENVIRONMENT,
                default=default_environment,
            )
        ] = _api_environment_selector()
        fields[vol.Required(CONF_SETUP_KEY)] = str
        fields[vol.Optional(CONF_CPIN)] = str
        return vol.Schema(fields)


class SentrymoOptionsFlow(config_entries.OptionsFlow):
    """Handle Sentrymo options."""

    def __init__(
        self, config_entry: config_entries.ConfigEntry
    ) -> None:
        """Initialize the options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_API_URL: _resolve_api_url(
                        str(user_input[CONF_API_ENVIRONMENT])
                    ),
                },
            )

        current_api_url = self.config_entry.options.get(
            CONF_API_URL,
            self.config_entry.data.get(CONF_API_URL),
        )
        current_environment = _environment_from_api_url(
            current_api_url
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_ENVIRONMENT,
                    default=current_environment,
                ): _api_environment_selector(),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
