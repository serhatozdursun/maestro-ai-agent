"""Deterministic inference of target hints from a :class:`StepIntent`."""

from __future__ import annotations

import re

from maestro_ai_agent.domain.enums import ActionType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.tap_qualifier import find_tap_qualifier_in_text
from maestro_ai_agent.domain.selectors.target_hints import ControlKind, TargetHints

_QUOTED = re.compile(r"['\"](?P<body>[^'\"]+)['\"]")
_TAP_TAIL = re.compile(
    r"^\s*(?:tap|press|click)\s+(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)

_SIGNIN = ("sign in", "sign-in", "login", "log in", "log-in", "register")
_CONTINUE = ("continue", "next", "skip")
_CART = ("add to cart", "add bag", "add to bag", "buy now", "checkout")
_SEARCH = ("search", "find")


def _tap_target_without_quotes(raw: str) -> str | None:
    """
    Best-effort label after tap/press/click when the step omits quotes (e.g. ``Tap UK``).

    Quoted literals are handled separately via ``_QUOTED``; this only fills the gap for
    short unquoted tails so selector generation has a non-empty hint token.
    """
    m = _TAP_TAIL.match(raw.strip())
    if not m:
        return None
    rest = m.group(1).strip()
    if not rest:
        return None
    if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "'\"":
        return rest[1:-1].strip() or None
    return rest


def infer_target_hints(intent: StepIntent) -> TargetHints:
    """
    Derive modest keyword/text hints from the intent text and validation goals.

    This is intentionally shallow and regex-driven so it can be replaced or augmented
    by an LLM later without changing ranking plumbing.
    """
    desired: list[str] = []
    for match in _QUOTED.finditer(intent.raw_step_text):
        desired.append(match.group("body"))
    for goal in intent.validation_goals:
        if goal.target_hint:
            desired.append(goal.target_hint)
    if intent.primary_action is ActionType.TAP and not _QUOTED.search(intent.raw_step_text):
        tail = _tap_target_without_quotes(intent.raw_step_text)
        if tail:
            desired.append(tail)

    semantic: list[str] = []
    lower = intent.raw_step_text.lower()
    if any(token in lower for token in _SIGNIN):
        semantic.extend(["sign in", "login", "password", "email"])
    if any(token in lower for token in _CONTINUE):
        semantic.extend(["continue", "next"])
    if any(token in lower for token in _CART):
        semantic.extend(["add to cart", "cart", "bag"])
    if any(token in lower for token in _SEARCH):
        semantic.extend(["search"])

    control = ControlKind.UNKNOWN
    if intent.primary_action is ActionType.INPUT_TEXT:
        control = ControlKind.EDITTEXT
    elif intent.primary_action in (ActionType.ASSERT_VISIBLE, ActionType.ASSERT_NOT_VISIBLE):
        control = ControlKind.TEXTVIEW
    elif intent.primary_action is ActionType.TAP:
        control = ControlKind.BUTTON

    container_hint = intent.target_container_hint
    qualifier_raw = intent.target_qualifier_phrase_raw
    if intent.primary_action is ActionType.TAP:
        tq = find_tap_qualifier_in_text(intent.raw_step_text)
        if tq:
            if container_hint is None:
                container_hint = tq.container_hint
            if qualifier_raw is None:
                qualifier_raw = tq.qualifier_phrase_raw

    return TargetHints(
        desired_texts=_dedupe_preserve_order(desired),
        semantic_keywords=_dedupe_preserve_order(semantic),
        preferred_control_kind=control,
        container_hint=container_hint,
        qualifier_phrase_raw=qualifier_raw,
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        item = raw.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
