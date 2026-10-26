@docs/project-context.md
# skycomslovakia/sentrymo-home-assistant
Home Assistant Python custom integration (manifest domain sentrymo, config_flow, cloud_polling, hub type) exposing Sentrymo vehicle states and commands.

## Commands
- Install: `TODO: verify Python virtualenv / dependency setup`
- Run: `TODO: verify development Home Assistant harness`
- Test: `TODO: verify pytest invocation`
- Lint/format: `TODO: verify ruff/mypy or other lint config`
- Build: `TODO: verify HACS package/release`
- Migrate: `not applicable`

## Files and conventions
- custom_components/sentrymo/manifest.json; custom_components/sentrymo/ (runtime); HACS packaging files (unverified)
- Treat authentication tokens and device GPS data as sensitive.
- Preserve existing public /api/v1 contract and backward compatibility with deployed integrations.
- Never commit secrets, customer info or local .env/config content.
- Never edit built/generated files or production-applied DB migrations.
- Never bypass per-vehicle or user ACL checks for simplicity.
- Validate any (unverified) commands and JSON payloads from source before use.
