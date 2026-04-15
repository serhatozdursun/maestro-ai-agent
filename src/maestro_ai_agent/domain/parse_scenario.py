"""Deterministic first-pass parsing of natural-language scenarios into atomic lines."""

from __future__ import annotations

import re

from maestro_ai_agent.domain.scenario import ParsedScenario, ScenarioInput, ScenarioStep

_LEADING_ENUM = re.compile(
    r"^\s*(?:"
    r"[*\-•]+\s*"  # bullets
    r"|\d+[.)]\s*"  # numbered 1. or 1)
    r")\s*",
    flags=re.UNICODE,
)


def _strip_leading_marker(line: str) -> str:
    """Remove common Markdown or plain-text list markers from a line."""
    previous = None
    current = line
    # Repeat to handle nested markers like "1. - Do thing"
    while previous != current:
        previous = current
        current = _LEADING_ENUM.sub("", current)
    return current.strip()


def _iter_normalized_lines(text: str) -> tuple[list[tuple[int, str]], list[str]]:
    """Return (list of (source_line_no, normalized_text]), warnings)."""
    warnings: list[str] = []
    results: list[tuple[int, str]] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        normalized = _strip_leading_marker(stripped)
        if not normalized:
            warnings.append(f"Line {line_no} became empty after stripping markers; skipped.")
            continue
        results.append((line_no, normalized))
    if not results:
        warnings.append("No non-empty steps found after parsing.")
    return results, warnings


def parse_scenario_input(scenario_input: ScenarioInput) -> ParsedScenario:
    """
    Split scenario text into ordered :class:`ScenarioStep` rows.

    This is intentionally simple (newline-based, marker stripping) so it can be
    swapped for an LLM-assisted parser later without changing downstream models.
    """
    lines, warnings = _iter_normalized_lines(scenario_input.scenario_text)
    steps = [
        ScenarioStep(index=i, text=text, source_line=line_no)
        for i, (line_no, text) in enumerate(lines)
    ]
    return ParsedScenario(input=scenario_input, steps=steps, warnings=warnings)
