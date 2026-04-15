"""
Bridge canonical scenario understanding into :class:`ParsedScenario` for :func:`plan_intents`.

Deterministic only: maps each :class:`CanonicalStep` to one planner line. Prefers
``source_text`` when it is not shaped like a Gherkin clause header, so the
existing keyword-based planner sees the same imperative text the deterministic
parser derived from raw input.
"""

from __future__ import annotations

import re

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.scenario import ParsedScenario, ScenarioInput, ScenarioStep
from maestro_ai_agent.scenario.canonical_model import CanonicalScenario, CanonicalStep

_PARSER_NAME = "canonical_to_parsed_v1"
_GHERKIN_SHAPED = re.compile(
    r"^\s*(Given|When|Then|And|But|Scenario:)\s+",
    re.IGNORECASE,
)


def _is_gherkin_shaped_line(text: str) -> bool:
    return bool(_GHERKIN_SHAPED.match(text.strip()))


def canonical_step_to_planner_line(step: CanonicalStep) -> str:
    """
    Produce a single line of scenario text for :func:`plan_intents` heuristics.

    Does not re-run business rules from the deterministic parser; it only formats
    canonical fields into planner-friendly lines when ``source_text`` is absent
    or is a Gherkin clause (which the keyword planner does not classify well).
    """
    raw_src = (step.source_text or "").strip()
    if raw_src and not _is_gherkin_shaped_line(raw_src):
        return raw_src

    action = step.action.lower()
    target = (step.target or "").strip()
    value = (step.value or "").strip()

    if action == "tap" and target:
        if step.target_qualifier_phrase_raw and step.tap_qualifier_preposition:
            prep = step.tap_qualifier_preposition.strip().lower()
            if prep not in {"on", "in", "from"}:
                prep = "on"
            return f"Tap '{target}' {prep} {step.target_qualifier_phrase_raw}"
        return f"Tap '{target}'"
    if action == "assert" and target:
        return f'Verify "{target}" is visible'
    if action in ("input", "input_text"):
        if value:
            return f"Input '{value}'"
        if target:
            return f"Enter '{target}'"
        return "Input text"
    if action == "launch_app" or action in ("launch", "login"):
        return "Launch app"
    if action == "assert_visible" and target:
        return f'Assert visible "{target}"'
    if action == "assert_not_visible" and target:
        return f'Assert not visible "{target}"'
    if action == "press_key" and value:
        if value.lower() == "enter":
            return "Press Enter"
        return f"Press key '{value.lower()}'"
    if action == "scroll" and value:
        return f"Scroll {value.strip().capitalize()}"
    if action == "scroll_until_visible" and target:
        return f"Scroll until visible '{target}'"
    if action == "dismiss_blocker":
        return "Dismiss any popup and continue"
    if action == "back":
        return "go back"
    if action == "swipe":
        return "swipe up"
    if action == "search" and target:
        return f"Tap '{target}'"
    if action == "navigate" and target:
        return f"Tap '{target}'"
    if action == "add_to_cart":
        return "Tap 'Cart'"
    if action == "open_first_product":
        return "Tap first product"
    if target:
        return f"Tap '{target}'"
    if value:
        return f"Input '{value}'"
    if raw_src:
        return raw_src
    return f"unknown step ({action})"


def build_parsed_scenario_from_canonical(
    canonical: CanonicalScenario,
    *,
    app_id: str,
    platform: Platform,
    title: str | None = None,
) -> ParsedScenario:
    """
    Build the same shape :func:`parse_scenario_input` produces, without re-splitting raw text.

    The legacy path ``ScenarioInput`` + :func:`parse_scenario_input` remains available;
    callers that already have a :class:`CanonicalScenario` can use this adapter instead.
    """
    if not canonical.steps:
        msg = "CanonicalScenario has no steps; cannot build ParsedScenario."
        raise ValueError(msg)

    lines = [canonical_step_to_planner_line(s) for s in canonical.steps]
    body = "\n".join(lines).strip()
    scenario_input = ScenarioInput(
        scenario_text=body,
        app_id=app_id,
        platform=platform,
        title=title if title is not None else canonical.title,
    )
    merged_warnings = list(canonical.warnings)
    steps_out = [
        ScenarioStep(
            index=i,
            text=line,
            source_line=i + 1,
            canonical_action=canonical.steps[i].action,
        )
        for i, line in enumerate(lines)
    ]
    return ParsedScenario(
        input=scenario_input,
        steps=steps_out,
        parser_name=_PARSER_NAME,
        warnings=merged_warnings,
    )
