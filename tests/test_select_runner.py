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

CONFIG = Config(wsl_label="blackhole")
NO_GITHUB = Config(wsl_label="blackhole", github_hosted=False)


def runner(label: str, online: bool = True, busy: bool = False) -> Runner:
    return Runner(
        name=label,
        online=online,
        busy=busy,
        labels=frozenset({"self-hosted", "Linux", "X64", label}),
    )


class ChooseRunnerTest(unittest.TestCase):
    """Verify the wsl > github priority (VPS runners dropped 2026-11-23)."""

    def test_idle_wsl_wins(self) -> None:
        runners = [runner("blackhole"), runner("sentrymo-shared")]
        self.assertEqual(choose(CONFIG, runners)[0], "wsl")
        self.assertEqual(CONFIG.runs_on("wsl"), ["self-hosted", "blackhole"])

    def test_offline_or_busy_wsl_falls_back_to_github(self) -> None:
        self.assertEqual(choose(CONFIG, [runner("blackhole", online=False)])[0], "github")
        self.assertEqual(choose(CONFIG, [runner("blackhole", busy=True)])[0], "github")
        self.assertEqual(CONFIG.runs_on("github"), "ubuntu-latest")

    def test_shared_vps_runner_is_never_picked(self) -> None:
        runners = [runner("blackhole", online=False), runner("sentrymo-shared")]
        self.assertEqual(choose(CONFIG, runners)[0], "github")
        self.assertEqual(choose(NO_GITHUB, runners)[0], "wsl")

    def test_github_disabled_queues_on_wsl(self) -> None:
        self.assertEqual(choose(NO_GITHUB, [runner("blackhole", busy=True)])[0], "wsl")
        self.assertEqual(choose(NO_GITHUB, [])[0], "wsl")
        self.assertEqual(choose(NO_GITHUB, None)[0], "wsl")

    def test_unknown_status_uses_github(self) -> None:
        self.assertEqual(choose(CONFIG, None)[0], "github")

    def test_fork_always_uses_github(self) -> None:
        forced = Config(wsl_label="blackhole", force="wsl")
        self.assertEqual(choose(forced, [runner("blackhole")], from_fork=True)[0], "github")

    def test_force(self) -> None:
        forced = Config(wsl_label="blackhole", force="github")
        self.assertEqual(choose(forced, [runner("blackhole")])[0], "github")


if __name__ == "__main__":
    unittest.main()
