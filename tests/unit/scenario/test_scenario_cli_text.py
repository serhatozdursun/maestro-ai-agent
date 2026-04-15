"""CLI scenario text resolution (mutually exclusive sources)."""

from __future__ import annotations

from pathlib import Path

import pytest

from maestro_ai_agent.scenario.scenario_cli_text import (
    ScenarioInputSourceError,
    join_cli_steps,
    resolve_scenario_text_for_cli,
)


def test_join_cli_steps_preserves_order() -> None:
    assert join_cli_steps(["Enter 'a'", "Press Enter"]) == "Enter 'a'\nPress Enter"


def test_resolve_scenario_file_only(tmp_path: Path) -> None:
    p = tmp_path / "s.txt"
    p.write_text("Tap 'OK'\nPress Enter\n", encoding="utf-8")
    text = resolve_scenario_text_for_cli(scenario_file=p, scenario=None, steps=[])
    assert text == "Tap 'OK'\nPress Enter\n"


def test_resolve_scenario_inline_only() -> None:
    text = resolve_scenario_text_for_cli(
        scenario_file=None,
        scenario="  Enter 'x'\nPress Enter  ",
        steps=[],
    )
    assert text == "Enter 'x'\nPress Enter"


def test_resolve_steps_only() -> None:
    text = resolve_scenario_text_for_cli(
        scenario_file=None,
        scenario=None,
        steps=["Enter 'shoe'", "Press Enter"],
    )
    assert text == "Enter 'shoe'\nPress Enter"


def test_three_surfaces_same_text(tmp_path: Path) -> None:
    body = "Enter 'shoe'\nPress Enter"
    p = tmp_path / "t.txt"
    p.write_text(body + "\n", encoding="utf-8")
    a = resolve_scenario_text_for_cli(scenario_file=p, scenario=None, steps=[]).strip()
    b = resolve_scenario_text_for_cli(scenario_file=None, scenario=body, steps=[]).strip()
    c = resolve_scenario_text_for_cli(
        scenario_file=None,
        scenario=None,
        steps=["Enter 'shoe'", "Press Enter"],
    ).strip()
    assert a == b == c


def test_multiple_sources_rejected(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ScenarioInputSourceError, match="mutually exclusive"):
        resolve_scenario_text_for_cli(scenario_file=p, scenario="y", steps=[])


def test_zero_sources_rejected() -> None:
    with pytest.raises(ScenarioInputSourceError, match="exactly one"):
        resolve_scenario_text_for_cli(scenario_file=None, scenario=None, steps=[])
