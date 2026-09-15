# Sentrymo Home Assistant Integration

Custom Home Assistant integration for Sentrymo vehicle status, location and supported remote commands.

## Requirements and architecture

Home Assistant communicates only with the dedicated Sentrymo Home Assistant API:

```text
Home Assistant -> ha-api.sentrymo.eu/api/v1 -> Sentrymo
```

The integration requires the server-side `home_assistant` entitlement for each accessible vehicle. It is currently included in the Legend package. The client does not infer access from a package name or ID; the API remains authoritative for entitlement, ownership, vehicle allowlists, scopes and privacy.

## Installation

### HACS custom repository

1. Open HACS.
2. Add this repository as a custom repository in the `Integration` category.
3. Install `Sentrymo` and restart Home Assistant.
4. Go to Settings -> Devices & services -> Add integration -> Sentrymo.

## Pairing and locally stored credentials

Generate Home Assistant access in the Sentrymo mobile app, then enter the selected environment, one-time pairing key and optional 4-digit CPIN in the config flow.

The one-time pairing key is exchanged for an access token and refresh token and is not persisted for a new config entry. Home Assistant stores these values in its config entry:

- API environment URL;
- access token, refresh token and access-token expiry;
- integration name;
- CPIN, when supplied.

The CPIN is needed only for command requests. It is stored locally because the current command API requires it on every request. The integration does not log it, include it in exception text, expose it as an entity attribute or provide it through diagnostics. Protect Home Assistant storage and backups as credentials.

## Read entities

The integration creates a device per currently authorized vehicle. Depending on server capabilities and available data, it exposes:

- `device_tracker` for vehicle location;
- sensors for speed, voltages, internal battery, GSM signal, odometer, fuel, timestamps and other telemetry;
- binary sensors for movement, ignition, protection, alarm, connectivity, crash and supported vehicle states;
- a refresh button.

Every update first obtains an authorized `/vehicles` response. State segments and their cache are filtered through that vehicle set. A cached segment cannot recreate a removed, unentitled or disallowed vehicle.

If a vehicle disappears, its existing Home Assistant entities and device-registry record are retained non-destructively and become unavailable. They can recover with the same identity if the vehicle is authorized again.

## Commands

Command controls are exposed only when the API reports the matching read and command capabilities and a CPIN is configured:

- protection mode select and `sentrymo.set_protection_mode`;
- immobilizer switch and `sentrymo.set_immobilizer`;
- accessory switch and `sentrymo.set_accessory`.

Read access is independent from command scope. A denied or disabled command remains a command error and does not break read entities or start reauthentication.

The API currently returns `accepted` for protection requests and `queued` for output requests. These responses acknowledge receipt; they do not guarantee physical execution. Queued output commands are therefore not shown as completed optimistically. The next read snapshot reconciles the actual state.

## Authentication and access changes

- An expired or invalid access token is refreshed once and the original request is retried once.
- `invalid_authentication`, invalid refresh credentials and explicit `integration_revoked` start the standard Home Assistant reauthentication flow.
- On `integration_revoked`, local tokens and segment cache are invalidated before a new pairing is requested.
- Entitlement, permission, vehicle, scope, capability and rate-limit errors never start reauthentication.

If the `home_assistant` entitlement ends while a token is still cryptographically valid, the next authorized request is rejected immediately. The config entry remains present, existing entities become unavailable, cached segments are discarded and Home Assistant reports that the feature is unavailable in the current package. Normal coordinator polling may detect later restoration; the client does not run a login or immediate retry loop.

A denied state scope affects only entities backed by that state segment. Temporary network/server failures and rate limiting may retain bounded cached values, but affected entities are marked unavailable until a current segment succeeds. Cache is never used after entitlement, permission, revocation, vehicle or scope denial.

## Troubleshooting

- **Pairing key expired:** generate a new one-time key in the Sentrymo app.
- **Reauthentication required:** complete the repair flow with a new pairing key. Revoked integrations cannot reuse their old session.
- **Feature unavailable:** the account or vehicle does not currently have the server-side `home_assistant` entitlement. It is currently part of Legend.
- **Permission or scope denied:** review the integration owner, allowed vehicles and granted scopes in Sentrymo.
- **Command unavailable:** confirm command scope, vehicle capability, integration command setting and locally configured CPIN.
- **Rate limited or temporary outage:** wait for the next scheduled coordinator update.

## Status

This integration is HACS-ready and under active development.
