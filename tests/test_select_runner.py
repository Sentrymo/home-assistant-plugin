"""Tests for the CI runner priority selector."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "select_runner.py"
SPEC = importlib.util.spec_from_file_location("select_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
Config = MODULE.Config
Runner = MODULE.Runner
choose = MODULE.choose

CONFIG = Config(
    wsl_label="blackhole",
    repo_label="home-assistant-plugin",
    shared_label="sentrymo-shared",
)
NO_GITHUB = Config(
    wsl_label="blackhole",
    repo_label="home-assistant-plugin",
    shared_label="sentrymo-shared",
    github_hosted=False,
)


def runner(label: str, online: bool = True, busy: bool = False) -> Runner:
    return Runner(
        name=label,
        online=online,
        busy=busy,
        labels=frozenset({"self-hosted", "Linux", "X64", label}),
    )


class ChooseRunnerTest(unittest.TestCase):
    """Verify the wsl > github > repo VPS > shared VPS priority."""

    def test_idle_wsl_wins(self) -> None:
        runners = [runner("blackhole"), runner("home-assistant-plugin"), runner("sentrymo-shared")]
        self.assertEqual(choose(CONFIG, runners)[0], "wsl")
        self.assertEqual(CONFIG.runs_on("wsl"), ["self-hosted", "blackhole"])

    def test_offline_or_busy_wsl_falls_back_to_github(self) -> None:
        self.assertEqual(choose(CONFIG, [runner("blackhole", online=False)])[0], "github")
        self.assertEqual(choose(CONFIG, [runner("blackhole", busy=True)])[0], "github")
        self.assertEqual(CONFIG.runs_on("github"), "ubuntu-latest")

    def test_repo_vps_before_shared_when_github_disabled(self) -> None:
        runners = [runner("home-assistant-plugin"), runner("sentrymo-shared")]
        self.assertEqual(choose(NO_GITHUB, runners)[0], "repo")

    def test_shared_when_repo_has_no_runner(self) -> None:
        runners = [runner("blackhole", online=False), runner("sentrymo-shared")]
        self.assertEqual(choose(NO_GITHUB, runners)[0], "shared")
        self.assertEqual(NO_GITHUB.runs_on("shared"), ["self-hosted", "sentrymo-shared"])

    def test_idle_shared_beats_busy_repo(self) -> None:
        runners = [runner("home-assistant-plugin", busy=True), runner("sentrymo-shared")]
        self.assertEqual(choose(NO_GITHUB, runners)[0], "shared")

    def test_busy_repo_beats_busy_shared(self) -> None:
        runners = [
            runner("home-assistant-plugin", busy=True),
            runner("sentrymo-shared", busy=True),
        ]
        self.assertEqual(choose(NO_GITHUB, runners)[0], "repo")

    def test_nothing_online_queues_on_shared(self) -> None:
        self.assertEqual(choose(NO_GITHUB, [])[0], "shared")

    def test_unknown_status_uses_github(self) -> None:
        self.assertEqual(choose(CONFIG, None)[0], "github")

    def test_fork_always_uses_github(self) -> None:
        forced = Config(
            wsl_label="blackhole",
            repo_label="home-assistant-plugin",
            shared_label="sentrymo-shared",
            force="wsl",
        )
        self.assertEqual(choose(forced, [runner("blackhole")], from_fork=True)[0], "github")

    def test_force(self) -> None:
        forced = Config(
            wsl_label="blackhole",
            repo_label="home-assistant-plugin",
            shared_label="sentrymo-shared",
            force="shared",
        )
        self.assertEqual(choose(forced, [runner("blackhole")])[0], "shared")


if __name__ == "__main__":
    unittest.main()
