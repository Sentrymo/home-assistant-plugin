#!/usr/bin/env bash
# Registers a shared Sentrymo organization runner on the VPS.
#
# Follows the existing VPS layout: /opt/actions-runner-<name>, owned by a
# dedicated user gh-<name>, running as a systemd service. The runner is
# registered at the organization (not a repository), so every Sentrymo
# repository in the runner group can use it with:
#   runs-on: [self-hosted, sentrymo-shared]
#
# Usage (as root on the VPS):
#   RUNNER_TOKEN=<registration token> ./setup-shared-runner.sh [instance]
#
#   instance   optional suffix for more parallel runners: 2 -> actions-runner-shared-2
#
# The registration token comes from GitHub: Sentrymo organization
# -> Settings -> Actions -> Runners -> New runner -> New self-hosted runner
# (the value after --token). It is valid for one hour and only for registering.
set -euo pipefail

ORG_URL="${ORG_URL:-https://github.com/Sentrymo}"
RUNNER_LABELS="${RUNNER_LABELS:-sentrymo-shared}"
RUNNER_GROUP="${RUNNER_GROUP:-Default}"
RUNNER_USER="${RUNNER_USER:-gh-shared}"
INSTANCE="${1:-}"

[[ "$(id -u)" -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ -n "${RUNNER_TOKEN:-}" ]] || { echo "Set RUNNER_TOKEN to the organization registration token." >&2; exit 1; }

name="shared${INSTANCE:+-${INSTANCE}}"
dir="/opt/actions-runner-${name}"
runner_name="${RUNNER_NAME:-$(hostname -s)-${name}}"

echo "==> Prerequisites"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl jq tar git zip unzip python3 python3-venv ca-certificates >/dev/null
if ! command -v gh >/dev/null; then
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update -qq && apt-get install -y -qq gh >/dev/null
fi

echo "==> User ${RUNNER_USER}"
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${RUNNER_USER}"
fi
# Same as the per-repository runners: jobs build images with Docker.
if getent group docker >/dev/null; then
  usermod -aG docker "${RUNNER_USER}"
fi

echo "==> Runner in ${dir}"
if [[ -f "${dir}/.runner" ]]; then
  echo "${dir} is already configured. Remove it first (./config.sh remove) or pick another instance." >&2
  exit 1
fi
install -d -o "${RUNNER_USER}" -g "${RUNNER_USER}" "${dir}"

case "$(uname -m)" in
  x86_64) arch=x64 ;;
  aarch64) arch=arm64 ;;
  *) echo "Unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac
version="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/^v//')"
archive="actions-runner-linux-${arch}-${version}.tar.gz"
curl -fsSL -o "/tmp/${archive}" "https://github.com/actions/runner/releases/download/v${version}/${archive}"
tar -xzf "/tmp/${archive}" -C "${dir}"
rm -f "/tmp/${archive}"
chown -R "${RUNNER_USER}:${RUNNER_USER}" "${dir}"
"${dir}/bin/installdependencies.sh" >/dev/null

echo "==> Register ${runner_name} at ${ORG_URL} (labels: ${RUNNER_LABELS}, group: ${RUNNER_GROUP})"
sudo -u "${RUNNER_USER}" -H bash -c "cd '${dir}' && ./config.sh --unattended --replace \
  --url '${ORG_URL}' --token '${RUNNER_TOKEN}' \
  --name '${runner_name}' --labels '${RUNNER_LABELS}' --runnergroup '${RUNNER_GROUP}' \
  --work _work"

echo "==> systemd service"
(cd "${dir}" && ./svc.sh install "${RUNNER_USER}" && ./svc.sh start)

echo "Done. Check it under Sentrymo -> Settings -> Actions -> Runners (status Idle)."
