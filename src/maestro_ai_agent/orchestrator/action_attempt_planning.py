"""Derive planned action attempts from ranked selector output (no execution)."""

from __future__ import annotations

import re

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.planning import quoted_literal_from_step_text
from maestro_ai_agent.domain.selectors.ranking_types import SelectorRankingResult
from maestro_ai_agent.orchestrator.models import PlannedActionAttempt

# Synthetic primary when INPUT_TEXT has a quoted literal but ranking found no target field.
DIRECT_INPUT_TEXT_CANDIDATE_ID = "direct_input_text"
DIRECT_INLINE_FLOW_CANDIDATE_ID = "direct_inline_flow"
DIRECT_ASSERT_SURFACE_ID = "direct_assert_surface"


def _flow_expression(tag: str, payload: str) -> str:
    """Sentinel expression consumed by execution mapping for bounded ``run_flow`` YAML."""
    safe = (payload or "").replace("|", "/")
    return f"__inline_flow__|{tag}|{safe}"


def _infer_press_key_token(raw: str) -> str | None:
    low = raw.strip().lower()
    if re.match(r"^press\s+enter\b", low):
        return "enter"
    m = re.match(r"^press\s+key\s+['\"]?([^'\"]+)['\"]?", low)
    if m:
        return m.group(1).strip().lower().replace(" ", "")
    return None


def _infer_scroll_direction(raw: str) -> str:
    low = raw.lower()
    m = re.search(r"scroll\s+(down|up|left|right)\b", low)
    if m:
        return m.group(1)
    if "scrolldown" in low.replace(" ", ""):
        return "down"
    if "scrollup" in low.replace(" ", ""):
        return "up"
    return "down"


_SWIPE_DIR = r"(left|right|up|down)"
_RE_SWIPE_PLAIN = re.compile(rf"(?i)^\s*swipe\s+{_SWIPE_DIR}\s*$")
_RE_SWIPE_ON = re.compile(
    rf"(?i)^\s*swipe\s+{_SWIPE_DIR}\s+on\s+['\"](?P<label>[^'\"]+)['\"]\s*$",
)
_RE_SWIPE_QUOTED_THEN_DIR = re.compile(
    r"(?i)^\s*swipe\s+['\"](?P<label>[^'\"]+)['\"]\s+(?P<dir>left|right|up|down)\s*$",
)

# Payload delimiter for ``swipe_on_text`` inline marker (not replaced by ``_flow_expression``).
_SWIPE_ON_TEXT_SEP = "\x1f"


def _parse_swipe_grammar_step(raw: str) -> tuple[str, str | None] | None:
    """
    Return ``(direction, element_text_or_none)`` for supported grammar swipes.

    Plain: ``Swipe left``. Targeted (quoted label only): ``Swipe left on 'Card'``,
    ``Swipe 'Card' left``.
    """
    s = raw.strip()
    m_on = _RE_SWIPE_ON.match(s)
    if m_on:
        return m_on.group(1).lower(), (m_on.group("label") or "").strip() or None
    m_q = _RE_SWIPE_QUOTED_THEN_DIR.match(s)
    if m_q:
        return (
            (m_q.group("dir") or "").lower(),
            (m_q.group("label") or "").strip() or None,
        )
    m_plain = _RE_SWIPE_PLAIN.match(s)
    if m_plain:
        return m_plain.group(1).lower(), None
    return None


def _try_scroll_until_visible_with_ranked_selector(
    *,
    intent: StepIntent,
    ranking: SelectorRankingResult,
    scenario_step_index: int,
    raw_step_text: str,
) -> PlannedActionAttempt | None:
    """Prefer ranked id/text primary for ``scrollUntilVisible`` over quoted text alone."""
    if intent.primary_action is not ActionType.SCROLL_UNTIL_VISIBLE:
        return None
    lit = quoted_literal_from_step_text(raw_step_text)
    if not lit or not lit.strip():
        return None
    primary = ranking.primary
    if primary is None:
        return None
    st = primary.candidate.selector_type
    if st not in (SelectorType.ID, SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        return None
    expr = (primary.candidate.expression or "").strip()
    if not expr:
        return None
    payload = f"{st.value}{_SWIPE_ON_TEXT_SEP}{expr}"
    return PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=scenario_step_index,
        action=ActionType.SCROLL_UNTIL_VISIBLE,
        chosen_candidate_id=primary.candidate.candidate_id,
        expression=_flow_expression("scroll_until_ranked", payload),
        selector_type=st,
        score=primary.score,
        rank_position=0,
        explanation_summary=(
            f"Maestro run_flow (scrollUntilVisible from ranked {st.value} selector) "
            "when step names a quoted target."
        ),
    )


def _try_assert_with_ranked_selector(
    *,
    intent: StepIntent,
    ranking: SelectorRankingResult,
    scenario_step_index: int,
    raw_step_text: str,
) -> PlannedActionAttempt | None:
    """Prefer ranked id/text primary for hierarchy asserts over quoted literal text alone."""
    if intent.primary_action not in (ActionType.ASSERT_VISIBLE, ActionType.ASSERT_NOT_VISIBLE):
        return None
    lit = quoted_literal_from_step_text(raw_step_text)
    if lit is None or not lit.strip():
        return None
    primary = ranking.primary
    if primary is None:
        return None
    st = primary.candidate.selector_type
    if st not in (SelectorType.ID, SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        return None
    expr = (primary.candidate.expression or "").strip()
    if not expr:
        return None
    return PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=scenario_step_index,
        action=intent.primary_action,
        chosen_candidate_id=primary.candidate.candidate_id,
        expression=expr,
        selector_type=st,
        score=primary.score,
        rank_position=0,
        explanation_summary=(
            f"Hierarchy assert from ranked {st.value} selector (quoted literal also present)."
        ),
    )


def _try_targeted_swipe_with_ranked_selector(
    *,
    intent: StepIntent,
    ranking: SelectorRankingResult,
    scenario_step_index: int,
    raw_step_text: str,
) -> PlannedActionAttempt | None:
    """
    When the step is a targeted grammar swipe and ranking produced a primary, prefer that
    selector (id / text family) for ``swipe.from`` instead of the quoted step label alone.
    """
    if intent.primary_action is not ActionType.SWIPE:
        return None
    parsed = _parse_swipe_grammar_step(raw_step_text)
    if not parsed:
        return None
    direction, target = parsed
    if not target:
        return None
    primary = ranking.primary
    if primary is None:
        return None
    st = primary.candidate.selector_type
    if st not in (SelectorType.ID, SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        return None
    expr = (primary.candidate.expression or "").strip()
    if not expr:
        return None
    payload = f"{direction}{_SWIPE_ON_TEXT_SEP}{st.value}{_SWIPE_ON_TEXT_SEP}{expr}"
    return PlannedActionAttempt(
        intent_id=intent.intent_id,
        scenario_step_index=scenario_step_index,
        action=ActionType.SWIPE,
        chosen_candidate_id=primary.candidate.candidate_id,
        expression=_flow_expression("swipe_on_ranked", payload),
        selector_type=st,
        score=primary.score,
        rank_position=0,
        explanation_summary=(
            f"Maestro run_flow (swipe from ranked {st.value} selector) "
            "with direction from grammar step."
        ),
    )


_GRAMMAR_SYNTHETIC_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.PRESS_KEY,
        ActionType.SCROLL,
        ActionType.SCROLL_UNTIL_VISIBLE,
        ActionType.SWIPE,
        ActionType.DISMISS_BLOCKER,
        ActionType.ASSERT_VISIBLE,
        ActionType.ASSERT_NOT_VISIBLE,
    },
)


def _try_grammar_synthetic_planned_attempt(
    *,
    intent: StepIntent,
    scenario_step_index: int,
    raw_step_text: str,
) -> PlannedActionAttempt | None:
    """Grammar-driven steps ignore ranked primaries (avoid mis-mapping e.g. ``Press Enter``)."""
    if intent.primary_action not in _GRAMMAR_SYNTHETIC_ACTIONS:
        return None
    if intent.primary_action is ActionType.PRESS_KEY:
        key = _infer_press_key_token(raw_step_text)
        if not key:
            return None
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=ActionType.PRESS_KEY,
            chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
            expression=_flow_expression("press_key", key),
            selector_type=SelectorType.TEXT,
            score=0.0,
            rank_position=0,
            explanation_summary="Maestro run_flow (pressKey) from grammar step.",
        )
    if intent.primary_action is ActionType.SCROLL:
        direction = _infer_scroll_direction(raw_step_text)
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=ActionType.SCROLL,
            chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
            expression=_flow_expression("scroll", direction),
            selector_type=SelectorType.TEXT,
            score=0.0,
            rank_position=0,
            explanation_summary="Maestro run_flow (swipe) from grammar scroll step.",
        )
    if intent.primary_action is ActionType.SWIPE:
        parsed = _parse_swipe_grammar_step(raw_step_text)
        if not parsed:
            return None
        direction, target = parsed
        if target:
            payload = f"{direction}{_SWIPE_ON_TEXT_SEP}{target}"
            return PlannedActionAttempt(
                intent_id=intent.intent_id,
                scenario_step_index=scenario_step_index,
                action=ActionType.SWIPE,
                chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
                expression=_flow_expression("swipe_on_text", payload),
                selector_type=SelectorType.TEXT,
                score=0.0,
                rank_position=0,
                explanation_summary=("Maestro run_flow (swipe from text) from grammar swipe step."),
            )
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=ActionType.SWIPE,
            chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
            expression=_flow_expression("scroll", direction),
            selector_type=SelectorType.TEXT,
            score=0.0,
            rank_position=0,
            explanation_summary=(
                "Maestro run_flow (directional swipe) from grammar swipe step; "
                "same YAML template as Scroll."
            ),
        )
    if intent.primary_action is ActionType.SCROLL_UNTIL_VISIBLE:
        lit = quoted_literal_from_step_text(raw_step_text)
        if not lit or not lit.strip():
            return None
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=ActionType.SCROLL_UNTIL_VISIBLE,
            chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
            expression=_flow_expression("scroll_until", lit.strip()),
            selector_type=SelectorType.TEXT,
            score=0.0,
            rank_position=0,
            explanation_summary="Maestro run_flow (scrollUntilVisible) from grammar step.",
        )
    if intent.primary_action is ActionType.DISMISS_BLOCKER:
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=ActionType.DISMISS_BLOCKER,
            chosen_candidate_id=DIRECT_INLINE_FLOW_CANDIDATE_ID,
            expression=_flow_expression("dismiss_blocker", ""),
            selector_type=SelectorType.TEXT,
            score=0.0,
            rank_position=0,
            explanation_summary=(
                "Runtime blocker registry (detect → resolve hierarchy tap → verify); "
                "not static run_flow YAML."
            ),
        )
    if intent.primary_action in (ActionType.ASSERT_VISIBLE, ActionType.ASSERT_NOT_VISIBLE):
        lit = quoted_literal_from_step_text(raw_step_text)
        if lit is None or not lit.strip():
            return None
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=intent.primary_action,
            chosen_candidate_id=DIRECT_ASSERT_SURFACE_ID,
            expression=lit.strip(),
            selector_type=SelectorType.TEXT,
            score=0.0,
            rank_position=0,
            explanation_summary="Hierarchy-only assert (no provider tap).",
        )
    return None


def plan_action_attempt_from_ranking(
    *,
    intent: StepIntent,
    ranking: SelectorRankingResult,
    scenario_step_index: int,
    raw_step_text: str,
) -> PlannedActionAttempt | None:
    """
    Choose the primary ranked candidate as the next planned attempt.

    Returns ``None`` when ranking produced no viable primary (honest planning).

    For ``INPUT_TEXT``, if there is no primary but the step text contains a quoted literal,
    still returns a synthetic attempt so execution can call MCP ``input_text`` against the
    focused field (Maestro semantics) without a ranked selector.
    """
    ranked_swipe = _try_targeted_swipe_with_ranked_selector(
        intent=intent,
        ranking=ranking,
        scenario_step_index=scenario_step_index,
        raw_step_text=raw_step_text,
    )
    if ranked_swipe is not None:
        return ranked_swipe

    ranked_scroll_until = _try_scroll_until_visible_with_ranked_selector(
        intent=intent,
        ranking=ranking,
        scenario_step_index=scenario_step_index,
        raw_step_text=raw_step_text,
    )
    if ranked_scroll_until is not None:
        return ranked_scroll_until

    ranked_assert = _try_assert_with_ranked_selector(
        intent=intent,
        ranking=ranking,
        scenario_step_index=scenario_step_index,
        raw_step_text=raw_step_text,
    )
    if ranked_assert is not None:
        return ranked_assert

    grammar = _try_grammar_synthetic_planned_attempt(
        intent=intent,
        scenario_step_index=scenario_step_index,
        raw_step_text=raw_step_text,
    )
    if grammar is not None:
        return grammar

    if intent.primary_action is ActionType.SWIPE:
        return None

    primary = ranking.primary
    if primary is not None:
        return PlannedActionAttempt(
            intent_id=intent.intent_id,
            scenario_step_index=scenario_step_index,
            action=intent.primary_action,
            chosen_candidate_id=primary.candidate.candidate_id,
            expression=primary.candidate.expression,
            selector_type=primary.candidate.selector_type,
            score=primary.score,
            rank_position=0,
            explanation_summary=primary.explanation.summary,
        )
    if intent.primary_action is ActionType.INPUT_TEXT:
        literal = quoted_literal_from_step_text(raw_step_text)
        if literal is not None and literal.strip():
            return PlannedActionAttempt(
                intent_id=intent.intent_id,
                scenario_step_index=scenario_step_index,
                action=ActionType.INPUT_TEXT,
                chosen_candidate_id=DIRECT_INPUT_TEXT_CANDIDATE_ID,
                expression=None,
                selector_type=SelectorType.TEXT,
                score=0.0,
                rank_position=0,
                explanation_summary=(
                    "Direct MCP input_text from quoted literal (focused field); "
                    "no ranked selector candidate."
                ),
            )
    return None
