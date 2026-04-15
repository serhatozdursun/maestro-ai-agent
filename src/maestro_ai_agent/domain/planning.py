"""
Lightweight deterministic planner: parsed lines -> intents + coarse validation goals.

This module uses keyword heuristics only. It does **not** understand full natural
language semantics; ``ActionType.UNKNOWN`` is used honestly when classification
is unclear. Replace or wrap with richer planners without changing domain models.
"""

from __future__ import annotations

import re
from uuid import uuid4

from maestro_ai_agent.domain.enums import ActionType, ValidationSignalType
from maestro_ai_agent.domain.intent import StepIntent, ValidationGoal
from maestro_ai_agent.domain.scenario import ParsedScenario, ScenarioStep
from maestro_ai_agent.domain.selectors.tap_qualifier import find_tap_qualifier_in_text

_ASSERT_PREFIXES = ("assert ", "verify ", "ensure ", "check that ")
_QUOTED = re.compile(r"['\"](?P<body>[^'\"]+)['\"]")

# Command-leading patterns only — avoid matching verbs inside quoted tap labels
# (e.g. ``Tap 'Swipe to like'`` must not become SWIPE).
_CMD_TAP = re.compile(r"^(?:tap|click|dokun)\s", re.IGNORECASE)
_CMD_SWIPE = re.compile(r"^swipe\b", re.IGNORECASE)
_CMD_INPUT = re.compile(r"^(?:enter|type|input)\b", re.IGNORECASE)
_CMD_PRESS_TAP = re.compile(r"^press\s+", re.IGNORECASE)


def _first_quoted_literal(text: str) -> str | None:
    match = _QUOTED.search(text)
    return match.group("body") if match else None


def quoted_literal_from_step_text(text: str) -> str | None:
    """Return the first single- or double-quoted literal in a scenario line, if any."""
    return _first_quoted_literal(text)


_CANONICAL_ACTION_TO_PLANNER: dict[str, ActionType] = {
    "tap": ActionType.TAP,
    "input": ActionType.INPUT_TEXT,
    "input_text": ActionType.INPUT_TEXT,
    "assert_visible": ActionType.ASSERT_VISIBLE,
    "assert_not_visible": ActionType.ASSERT_NOT_VISIBLE,
    # Imperative ``assert`` / verify lines normalize here; planner treats as visible assert.
    "assert": ActionType.ASSERT_VISIBLE,
    "scroll": ActionType.SCROLL,
    "scroll_until_visible": ActionType.SCROLL_UNTIL_VISIBLE,
    "press_key": ActionType.PRESS_KEY,
    "dismiss_blocker": ActionType.DISMISS_BLOCKER,
    "launch_app": ActionType.LAUNCH_APP,
    "launch": ActionType.LAUNCH_APP,
    "login": ActionType.LAUNCH_APP,
    "back": ActionType.BACK,
    "swipe": ActionType.SWIPE,
    # Canonical sugar that becomes tap-shaped planner lines
    "navigate": ActionType.TAP,
    "search": ActionType.TAP,
    "add_to_cart": ActionType.TAP,
    "open_first_product": ActionType.TAP,
}


def action_type_from_canonical_slug(slug: str | None) -> ActionType | None:
    """
    Map a :class:`~maestro_ai_agent.scenario.canonical_model.CanonicalStep` ``action`` slug
    to :class:`ActionType` when the canonical normalization path is authoritative.

    Returns ``None`` for unknown / narrative slugs so :func:`_infer_action` can fall back.
    """
    if slug is None or not str(slug).strip():
        return None
    s = str(slug).strip().lower()
    return _CANONICAL_ACTION_TO_PLANNER.get(s)


def _infer_action(text: str) -> ActionType:
    """Map a single scenario line to a coarse action (best-effort)."""
    lower = text.lower().strip()

    if re.search(r"(?i)^dismiss\b", lower):
        return ActionType.DISMISS_BLOCKER
    if re.search(r"(?i)assert\s*not\s*visible", lower) or lower.startswith("assertnotvisible"):
        return ActionType.ASSERT_NOT_VISIBLE
    if re.search(r"(?i)assert\s*visible\b", lower) or lower.startswith("assertvisible"):
        return ActionType.ASSERT_VISIBLE
    if re.search(r"(?i)^scrolluntilvisible\b", lower) or re.search(
        r"(?i)^scroll\s+until\s+visible\b",
        lower,
    ):
        return ActionType.SCROLL_UNTIL_VISIBLE
    if re.match(r"(?i)^scroll\b", lower):
        return ActionType.SCROLL
    if re.match(r"(?i)^press\s+enter\b", lower) or re.match(r"(?i)^press\s+key\b", lower):
        return ActionType.PRESS_KEY

    if lower.startswith(_ASSERT_PREFIXES) or lower.startswith("assert that"):
        return ActionType.ASSERT_VISIBLE
    if lower.startswith("launch ") or lower in {"launch app", "open app"}:
        return ActionType.LAUNCH_APP
    # Substring heuristic: ``" app" in lower`` may still match inside quoted literals;
    # canonical_action (launch_app) overrides when present.
    if lower.startswith("open ") and " app" in lower:
        return ActionType.LAUNCH_APP
    # Tap / click before swipe and input so quoted labels cannot steal the verb.
    if _CMD_TAP.match(lower):
        return ActionType.TAP
    if _CMD_SWIPE.match(lower):
        return ActionType.SWIPE
    if lower.startswith(("go back", "navigate back", "press back")) or lower == "back":
        return ActionType.BACK
    if _CMD_INPUT.match(lower):
        return ActionType.INPUT_TEXT
    # ``Press X`` taps (Press Enter / Press key already handled above).
    if _CMD_PRESS_TAP.match(lower):
        return ActionType.TAP
    return ActionType.UNKNOWN


def _validation_goals(step: ScenarioStep, action: ActionType) -> list[ValidationGoal]:
    text = step.text
    if action == ActionType.LAUNCH_APP:
        return [
            ValidationGoal(
                goal_id="vg-launch-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Root UI should appear after the app is launched.",
                target_hint=None,
            )
        ]
    if action == ActionType.TAP:
        return [
            ValidationGoal(
                goal_id="vg-tap-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description=(
                    "UI should update after the tap (hierarchy or visible landmarks change)."
                ),
                target_hint=_first_quoted_literal(text),
            )
        ]
    if action == ActionType.INPUT_TEXT:
        literal = _first_quoted_literal(text)
        return [
            ValidationGoal(
                goal_id="vg-input-1",
                signal=ValidationSignalType.TEXT_CONTAINS,
                description="Entered text should be reflected in the focused field or hierarchy.",
                target_hint=literal,
            )
        ]
    if action == ActionType.ASSERT_VISIBLE:
        literal = _first_quoted_literal(text)
        hint = (literal or text).strip()
        return [
            ValidationGoal(
                goal_id="vg-assert-1",
                signal=ValidationSignalType.TEXT_VISIBLE,
                description="Expected content should be visible on the current screen.",
                target_hint=hint,
            )
        ]
    if action == ActionType.ASSERT_NOT_VISIBLE:
        literal = _first_quoted_literal(text)
        hint = (literal or text).strip()
        return [
            ValidationGoal(
                goal_id="vg-assert-not-1",
                signal=ValidationSignalType.ELEMENT_ABSENT,
                description="Expected content should not be visible on the current screen.",
                target_hint=hint,
            )
        ]
    if action == ActionType.PRESS_KEY:
        return [
            ValidationGoal(
                goal_id="vg-press-key-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Hierarchy should change after the key press (best-effort).",
                target_hint=None,
            )
        ]
    if action == ActionType.SCROLL:
        return [
            ValidationGoal(
                goal_id="vg-scroll-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Scroll gesture should change visible hierarchy or scroll state.",
                target_hint=None,
            )
        ]
    if action == ActionType.SCROLL_UNTIL_VISIBLE:
        literal = _first_quoted_literal(text)
        return [
            ValidationGoal(
                goal_id="vg-scroll-until-1",
                signal=ValidationSignalType.TEXT_VISIBLE,
                description="Target text should become visible after scrolling.",
                target_hint=literal,
            )
        ]
    if action == ActionType.DISMISS_BLOCKER:
        return [
            ValidationGoal(
                goal_id="vg-dismiss-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Optional dismiss taps may change blocking UI; hierarchy may change.",
                target_hint=None,
            )
        ]
    if action == ActionType.BACK:
        return [
            ValidationGoal(
                goal_id="vg-back-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Navigating back should change the visible hierarchy.",
                target_hint=None,
            )
        ]
    if action == ActionType.SWIPE:
        return [
            ValidationGoal(
                goal_id="vg-swipe-1",
                signal=ValidationSignalType.HIERARCHY_CHANGED,
                description="Swipe should change scroll position or visible elements.",
                target_hint=None,
            )
        ]
    return [
        ValidationGoal(
            goal_id="vg-unknown-1",
            signal=ValidationSignalType.CUSTOM,
            description="Planner could not classify this step; validate outcome manually.",
            target_hint=None,
        )
    ]


def _goal_summary(action: ActionType, text: str) -> str:
    if action == ActionType.UNKNOWN:
        return f"Interpret and execute: {text}"
    return f"{action.value}: {text}"


def plan_intents(parsed: ParsedScenario) -> list[StepIntent]:
    """Produce :class:`StepIntent` rows for each parsed scenario step."""
    intents: list[StepIntent] = []
    for step in parsed.steps:
        from_canonical = action_type_from_canonical_slug(step.canonical_action)
        action = from_canonical if from_canonical is not None else _infer_action(step.text)
        goals = _validation_goals(step, action)
        tq = find_tap_qualifier_in_text(step.text) if action is ActionType.TAP else None
        intents.append(
            StepIntent(
                intent_id=uuid4(),
                scenario_step_index=step.index,
                primary_action=action,
                goal_summary=_goal_summary(action, step.text),
                raw_step_text=step.text,
                target_container_hint=tq.container_hint if tq else None,
                target_qualifier_phrase_raw=tq.qualifier_phrase_raw if tq else None,
                validation_goals=goals,
                selector_candidates=[],
            )
        )
    return intents
