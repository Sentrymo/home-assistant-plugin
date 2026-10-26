# Project context: Sentrymo/home-assistant-plugin

## Architecture
Home Assistant Python custom integration (manifest domain sentrymo, config_flow, cloud_polling, hub type) exposing Sentrymo vehicle states and commands.

## Domain model
HA config entry, coordinator, entity, vehicle, telemetry, protection, immobilizer, accessory; authentication tokens.

## Interfaces / inter-repo integration
Consumes Go Sentrymo/home-assitant-api stable /api/v1 auth exchange/refresh, profile/vehicles/state and command routes. No direct DB access; Laravel manages mobile setup token.
- Main counterpart: Sentrymo/home-assitant-api; Laravel API provisions links and authorizes user access; common device command state is backend-owned.
- Exact JSON payloads, token headers, refresh/rotation envelopes beyond named routes are **(unverified)** until checked against both implementations.

## Key decisions / rationale
Keep Home Assistant async I/O lifecycle, config_flow and token-refresh handling. Avoid storing raw refresh tokens in logs; no fake production telemetry in tests. Preserve HA entity unique IDs and API version during upgrades.
- Keep HA-specific access separate from general Laravel mobile API to avoid coupling HA polling to PHP session.
- Maintain stable entity IDs and API compatibility, robust refresh and rate limiting.
- Do not leak or mutate user data across environment or permission boundaries.

## Current state and technical debt
Manifest version 1.2.0. Actual HA test/lint packaging tasks and full exposed entities remain (unverified) pending source review.
- (unverified) Live QA/PROD image versions, API shape for optional sensors and outstanding HA issues.
- Audit existing tests and Home Assistant platform registration before refactors.

## Environments / deployment
- QA and PROD are separated. Backend Go image is deployed via GitOps/ArgoCD; Python custom integration uses HACS/HA installation.
- Local testing must use fake data and non-production identities.

## Current CI/CD
- GitHub Actions is the current Sentrymo CI platform (maintainer-confirmed). `ci.yml` runs the unit tests and `release.yml` publishes tagged releases; both pick their runner through `select-runner.yml` (blackhole WSL > GitHub-hosted > repo VPS > shared org VPS), see `docs/runners/README.md`.
- Home Assistant distribution is handled independently of Kubernetes/ArgoCD; the Go Home Assistant API backend uses Sentrymo GitOps deployments. TeamCity is retired.

## Source provenance
- Verified: manifest.json / go.mod and service README.
- Memory: rollout intentions, business entitlement decisions and Sentrymo system boundaries.
