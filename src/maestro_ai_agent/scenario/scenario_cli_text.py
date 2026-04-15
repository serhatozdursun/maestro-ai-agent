"""Resolve scenario text from mutually exclusive CLI input surfaces (deterministic)."""

from __future__ import annotations

from pathlib import Path


class ScenarioInputSourceError(ValueError):
    """More than one scenario source was supplied, or none."""


def join_cli_steps(steps: list[str]) -> str:
    """Join repeated ``--step`` values in order (one logical line per step)."""
    out: list[str] = []
    for s in steps:
        t = (s or "").strip()
        if not t:
            continue
        out.append(t)
    return "\n".join(out)


def resolve_scenario_text_for_cli(
    *,
    scenario_file: Path | None,
    scenario: str | None,
    steps: list[str],
) -> str:
    """
    Return raw scenario text from exactly one of:

    - ``scenario_file`` (UTF-8 file body, newline-separated steps)
    - ``scenario`` (inline multi-line string)
    - ``steps`` (non-empty list from repeated ``--step``)

    Raises :class:`ScenarioInputSourceError` if zero or more than one source is active.
    """
    file_active = scenario_file is not None
    scenario_active = scenario is not None and scenario.strip() != ""
    joined = join_cli_steps(steps)
    steps_active = joined != ""

    n = int(file_active) + int(scenario_active) + int(steps_active)
    if n == 0:
        msg = (
            "Provide exactly one scenario source: --scenario-file, --scenario, "
            "or one or more --step."
        )
        raise ScenarioInputSourceError(msg)
    if n > 1:
        msg = (
            "Scenario sources are mutually exclusive. Use only one of: "
            "--scenario-file, --scenario, or --step (repeatable)."
        )
        raise ScenarioInputSourceError(msg)

    if file_active:
        try:
            return scenario_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            msg = f"Scenario file not found: {scenario_file}"
            raise ScenarioInputSourceError(msg) from None
        except OSError as e:
            msg = f"Could not read scenario file {scenario_file}: {e}"
            raise ScenarioInputSourceError(msg) from e
    if scenario_active:
        return scenario.strip()
    return joined
