#!/usr/bin/env python3
"""Pick the runner for a CI job by Sentrymo's runner priority.

Priority:
  1. WSL self-hosted runner on blackhole (only when online and idle)
  2. GitHub-hosted runner (unless disabled with RUNNER_GITHUB_HOSTED=false)
  3. this repository's own VPS runner
  4. the shared organization VPS runner

GitHub Actions has no built-in fallback between runners, so this script asks
the API which self-hosted runners are online and writes the chosen `runs-on`
value (JSON) to $GITHUB_OUTPUT. Only stdlib is used so it also runs on a bare
self-hosted runner.

Environment:
  RUNNER_STATUS_TOKEN   token that can list runners (repo "Administration: read"
                        and org "Self-hosted runners: read"); without it the
                        script cannot see self-hosted runners and picks tier 2
  GITHUB_REPOSITORY     owner/repo (set by Actions)
  GITHUB_API_URL        API base (set by Actions)
  GITHUB_EVENT_PATH     event payload (set by Actions), used for the fork guard
  RUNNER_WSL_LABEL      label of the blackhole WSL runner (default: blackhole)
  RUNNER_REPO_LABEL     label of this repo's own VPS runner (default: repo name)
  RUNNER_SHARED_LABEL   label of the shared org VPS runner (default: sentrymo-shared)
  RUNNER_GITHUB_HOSTED  "false" skips tier 2 (e.g. a private repo out of minutes)
  RUNNER_GITHUB_LABEL   GitHub-hosted image (default: ubuntu-latest)
  RUNNER_FORCE          wsl | github | repo | shared: skip detection
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from typing import Any
import urllib.error
import urllib.request

TIERS = ("wsl", "github", "repo", "shared")


@dataclass(frozen=True)
class Runner:
    """A self-hosted runner as reported by the GitHub API."""

    name: str
    online: bool
    busy: bool
    labels: frozenset[str]


@dataclass(frozen=True)
class Config:
    """Labels and switches that decide each tier."""

    wsl_label: str
    repo_label: str
    shared_label: str
    github_label: str = "ubuntu-latest"
    github_hosted: bool = True
    force: str = ""

    def runs_on(self, tier: str) -> str | list[str]:
        """Return the runs-on value that targets a tier."""
        if tier == "github":
            return self.github_label
        label = {
            "wsl": self.wsl_label,
            "repo": self.repo_label,
            "shared": self.shared_label,
        }[tier]
        return ["self-hosted", label]


def _in_tier(runner: Runner, label: str) -> bool:
    return label in runner.labels


def choose(
    config: Config,
    runners: list[Runner] | None,
    from_fork: bool = False,
) -> tuple[str, str]:
    """Return (tier, reason). runners is None when the API was not reachable."""
    if from_fork:
        # Code from a fork must never run on our machines.
        return "github", "pull request from a fork"
    if config.force:
        return config.force, "forced by RUNNER_FORCE"
    if runners is None:
        if config.github_hosted:
            return "github", "self-hosted runner status unknown"
        return "shared", "runner status unknown and GitHub-hosted disabled"

    def online(label: str, idle: bool) -> bool:
        return any(
            r.online and (not idle or not r.busy) and _in_tier(r, label)
            for r in runners
        )

    if online(config.wsl_label, idle=True):
        return "wsl", "blackhole WSL runner is online and idle"
    if config.github_hosted:
        return "github", "blackhole WSL runner is offline or busy"
    for idle in (True, False):
        state = "idle" if idle else "busy"
        if online(config.repo_label, idle):
            return "repo", f"repository VPS runner is online ({state})"
        if online(config.shared_label, idle):
            return "shared", f"shared VPS runner is online ({state})"
    return "shared", "no self-hosted runner online; queueing on the shared runner"


def _get(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _list_runners(api: str, path: str, token: str) -> list[Runner]:
    runners: list[Runner] = []
    page = 1
    while True:
        data = _get(f"{api}/{path}/actions/runners?per_page=100&page={page}", token)
        for item in data.get("runners", []):
            runners.append(
                Runner(
                    name=item["name"],
                    online=item.get("status") == "online",
                    busy=bool(item.get("busy")),
                    labels=frozenset(label["name"] for label in item.get("labels", [])),
                )
            )
        if page * 100 >= data.get("total_count", 0):
            return runners
        page += 1


def fetch_runners(api: str, repository: str, token: str) -> list[Runner] | None:
    """Collect repository and organization runners; None if neither is visible."""
    owner = repository.split("/", 1)[0]
    runners: list[Runner] = []
    seen_any = False
    for path in (f"repos/{repository}", f"orgs/{owner}"):
        try:
            runners.extend(_list_runners(api, path, token))
            seen_any = True
        except (urllib.error.URLError, TimeoutError, ValueError) as err:
            print(f"::warning::Cannot list runners of {path}: {err}", file=sys.stderr)
    return runners if seen_any else None


def _from_fork(event_path: str | None, repository: str) -> bool:
    if not event_path or not os.path.exists(event_path):
        return False
    with open(event_path, encoding="utf-8") as file:
        event = json.load(file)
    head = (event.get("pull_request") or {}).get("head") or {}
    head_repo = (head.get("repo") or {}).get("full_name")
    return head_repo is not None and head_repo != repository


def main() -> int:
    env = os.environ
    repository = env["GITHUB_REPOSITORY"]
    force = env.get("RUNNER_FORCE", "").strip().lower()
    if force and force not in TIERS:
        print(f"::error::RUNNER_FORCE must be one of {', '.join(TIERS)}", file=sys.stderr)
        return 1
    config = Config(
        wsl_label=env.get("RUNNER_WSL_LABEL") or "blackhole",
        repo_label=env.get("RUNNER_REPO_LABEL") or repository.split("/", 1)[1],
        shared_label=env.get("RUNNER_SHARED_LABEL") or "sentrymo-shared",
        github_label=env.get("RUNNER_GITHUB_LABEL") or "ubuntu-latest",
        github_hosted=env.get("RUNNER_GITHUB_HOSTED", "").strip().lower() != "false",
        force=force,
    )

    from_fork = _from_fork(env.get("GITHUB_EVENT_PATH"), repository)
    runners: list[Runner] | None = None
    token = env.get("RUNNER_STATUS_TOKEN", "")
    if token and not from_fork and not force:
        runners = fetch_runners(
            env.get("GITHUB_API_URL", "https://api.github.com"), repository, token
        )
        for r in runners or []:
            state = "busy" if r.busy else "idle" if r.online else "offline"
            print(f"  {r.name}: {state}, labels {', '.join(sorted(r.labels))}")
    elif not token:
        print("::warning::RUNNER_STATUS_TOKEN is not set; self-hosted runners are not checked")

    tier, reason = choose(config, runners, from_fork)
    runs_on = json.dumps(config.runs_on(tier))
    print(f"Selected runner tier '{tier}' ({reason}): runs-on {runs_on}")

    if output := env.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as file:
            file.write(f"runs-on={runs_on}\ntier={tier}\n")
    if summary := env.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"Runner: **{tier}** ({reason}), `runs-on: {runs_on}`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
