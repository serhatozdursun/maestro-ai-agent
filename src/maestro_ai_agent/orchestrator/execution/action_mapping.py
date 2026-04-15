"""
Deterministic mapping from planner intent + ranked selector to Maestro provider calls.

Supports ``tap_on``, ``input_text``, bounded ``run_flow`` snippets for grammar steps,
and hierarchy-only asserts (no provider call).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.planning import quoted_literal_from_step_text
from maestro_ai_agent.orchestrator.action_attempt_planning import DIRECT_ASSERT_SURFACE_ID
from maestro_ai_agent.orchestrator.execution.inline_flow_yaml import (
    build_press_key_flow_yaml,
    build_scroll_until_visible_flow_yaml,
    build_scroll_until_visible_ranked_flow_yaml,
    build_swipe_flow_yaml,
    build_swipe_from_ranked_candidate_flow_yaml,
    build_swipe_from_text_flow_yaml,
)
from maestro_ai_agent.orchestrator.models import PlannedActionAttempt

INLINE_FLOW_PREFIX = "__inline_flow__|"


def try_parse_inline_flow_marker(expression: str | None) -> tuple[str, str] | None:
    """Parse ``__inline_flow__|tag|payload``; payload may be empty."""
    expr = (expression or "").strip()
    if not expr.startswith(INLINE_FLOW_PREFIX):
        return None
    rest = expr[len(INLINE_FLOW_PREFIX) :]
    if "|" not in rest:
        return rest, ""
    tag, _, payload = rest.partition("|")
    return tag, payload


class SupportedProviderAction(StrEnum):
    """Provider surface the execution layer may invoke."""

    TAP_ON = "tap_on"
    INPUT_TEXT = "input_text"
    RUN_FLOW = "run_flow"
    ASSERT_HIERARCHY = "assert_hierarchy"
    NONE = "none"


class ExecutionMappingDecision(BaseModel):
    """Outcome of deciding how (or whether) to invoke the provider."""

    action: SupportedProviderAction
    selector: str | None = None
    """Audit trail: canonical expression from ranking (e.g. ``id:bag``, ``text:Cart``)."""
    maestro_tap_id: str | None = None
    maestro_tap_text: str | None = None
    text_to_input: str | None = None
    flow_yaml: str | None = Field(
        default=None,
        description="Full Maestro document for ``run_flow`` (bounded templates only).",
    )
    assert_surface_literal: str | None = None
    """Quoted literal from the scenario line (hierarchy text assert surface)."""
    assert_surface_expect_visible: bool | None = None
    assert_ranked_expression: str | None = Field(
        default=None,
        description="Ranked selector expression when assert uses hierarchy id/text primary.",
    )
    assert_ranked_selector_type: SelectorType | None = Field(
        default=None,
        description="Selector type for ``assert_ranked_expression`` (id / text family).",
    )
    unsupported_reason: str | None = Field(
        default=None,
        description="Human-readable reason when action is NONE.",
    )


def parse_maestro_tap_arguments_from_planned(
    planned: PlannedActionAttempt,
) -> tuple[str | None, str | None, str | None]:
    """
    Map ranked tap candidate to Maestro MCP ``tap_on`` parameters (``id`` / ``text`` keys).

    Returns ``(tap_id, tap_text, unsupported_reason)``. Exactly one of tap_id/tap_text
    should be set when unsupported_reason is None.
    """
    expr = (planned.expression or "").strip()
    if not expr:
        return None, None, "Tap intent requires a non-empty selector expression for tap_on."

    lowered = expr.lower()
    if lowered.startswith("point:"):
        return None, None, "POINT selector is not supported for Maestro MCP tap_on."
    if planned.selector_type is SelectorType.POINT:
        return None, None, "POINT selector is not supported for Maestro MCP tap_on."

    if lowered.startswith("id:"):
        tid = expr[3:].strip()
        return (tid, None, None) if tid else (None, None, "Empty id value in id:… expression.")

    if lowered.startswith("text:"):
        ttxt = expr[5:].strip()
        if not ttxt:
            return None, None, "Empty text value in text:… expression."
        return None, ttxt, None

    if planned.selector_type is SelectorType.ID:
        return expr, None, None

    if planned.selector_type in (
        SelectorType.TEXT,
        SelectorType.RELATIONAL,
        SelectorType.TEXT_WITH_STATE,
    ):
        return None, expr, None

    return None, None, f"Unsupported selector_type for tap_on: {planned.selector_type.value}"


def _inline_flow_yaml_for_marker(*, app_id: str, tag: str, payload: str) -> str | None:
    if tag == "press_key":
        return build_press_key_flow_yaml(app_id=app_id, key=payload)
    if tag == "scroll":
        return build_swipe_flow_yaml(app_id=app_id, direction=payload or "down")
    if tag == "swipe_on_text":
        sep = "\x1f"
        if sep not in payload:
            return None
        direction, _, label = payload.partition(sep)
        direction = (direction or "").strip().lower()
        label = label.strip()
        if not label:
            return None
        return build_swipe_from_text_flow_yaml(
            app_id=app_id,
            element_text=label,
            direction=direction or "down",
        )
    if tag == "swipe_on_ranked":
        sep = "\x1f"
        parts = payload.split(sep)
        if len(parts) != 3:
            return None
        direction, kind_raw, expr = parts
        direction = (direction or "").strip().lower()
        expr = (expr or "").strip()
        if not expr:
            return None
        try:
            st = SelectorType(kind_raw.strip())
        except ValueError:
            return None
        return build_swipe_from_ranked_candidate_flow_yaml(
            app_id=app_id,
            direction=direction or "down",
            selector_type=st,
            expression=expr,
        )
    if tag == "scroll_until":
        if not (payload or "").strip():
            return None
        return build_scroll_until_visible_flow_yaml(app_id=app_id, element_text=payload.strip())
    if tag == "scroll_until_ranked":
        sep = "\x1f"
        parts = payload.split(sep)
        if len(parts) != 2:
            return None
        kind_raw, expr = parts
        expr = (expr or "").strip()
        if not expr:
            return None
        try:
            st = SelectorType(kind_raw.strip())
        except ValueError:
            return None
        return build_scroll_until_visible_ranked_flow_yaml(
            app_id=app_id,
            selector_type=st,
            expression=expr,
        )
    return None


def map_planned_to_provider_action(
    intent: StepIntent,
    planned: PlannedActionAttempt,
    *,
    raw_step_text: str,
    app_id: str | None = None,
) -> ExecutionMappingDecision:
    """
    Map a planned primary candidate to ``tap_on``, ``input_text``, bounded ``run_flow``,
    hierarchy assert, or refuse.
    """
    if intent.primary_action in (ActionType.ASSERT_VISIBLE, ActionType.ASSERT_NOT_VISIBLE):
        if planned.chosen_candidate_id == DIRECT_ASSERT_SURFACE_ID:
            lit = (planned.expression or "").strip()
            if not lit:
                return ExecutionMappingDecision(
                    action=SupportedProviderAction.NONE,
                    unsupported_reason=(
                        "Assert step requires a quoted literal in the scenario line."
                    ),
                )
            return ExecutionMappingDecision(
                action=SupportedProviderAction.ASSERT_HIERARCHY,
                assert_surface_literal=lit,
                assert_surface_expect_visible=intent.primary_action is ActionType.ASSERT_VISIBLE,
            )
        if planned.selector_type in (
            SelectorType.ID,
            SelectorType.TEXT,
            SelectorType.TEXT_WITH_STATE,
        ):
            expr = (planned.expression or "").strip()
            if not expr:
                return ExecutionMappingDecision(
                    action=SupportedProviderAction.NONE,
                    unsupported_reason="Ranked assert requires a non-empty selector expression.",
                )
            return ExecutionMappingDecision(
                action=SupportedProviderAction.ASSERT_HIERARCHY,
                assert_surface_literal=None,
                assert_surface_expect_visible=intent.primary_action is ActionType.ASSERT_VISIBLE,
                assert_ranked_expression=expr,
                assert_ranked_selector_type=planned.selector_type,
            )
        return ExecutionMappingDecision(
            action=SupportedProviderAction.NONE,
            unsupported_reason=(
                "Assert step expected quoted-literal (assert_surface) or ranked id/text planning."
            ),
        )

    marker = try_parse_inline_flow_marker(planned.expression)
    if marker is not None:
        tag, payload = marker
        if tag == "dismiss_blocker" and intent.primary_action is ActionType.DISMISS_BLOCKER:
            return ExecutionMappingDecision(
                action=SupportedProviderAction.NONE,
                unsupported_reason=(
                    "DISMISS_BLOCKER is executed by the runtime blocker engine in "
                    "ProviderStepExecutionService, not static run_flow YAML."
                ),
            )
        if not (app_id or "").strip():
            return ExecutionMappingDecision(
                action=SupportedProviderAction.NONE,
                unsupported_reason="Inline flow steps require app_id to build run_flow YAML.",
            )
        flow = _inline_flow_yaml_for_marker(app_id=app_id.strip(), tag=tag, payload=payload)
        if not flow:
            return ExecutionMappingDecision(
                action=SupportedProviderAction.NONE,
                unsupported_reason=f"Unknown or empty inline flow tag: {tag!r}.",
            )
        return ExecutionMappingDecision(
            action=SupportedProviderAction.RUN_FLOW,
            flow_yaml=flow,
        )

    if intent.primary_action is ActionType.TAP:
        tap_id, tap_text, tap_reason = parse_maestro_tap_arguments_from_planned(planned)
        if tap_reason:
            return ExecutionMappingDecision(
                action=SupportedProviderAction.NONE,
                unsupported_reason=tap_reason,
            )
        return ExecutionMappingDecision(
            action=SupportedProviderAction.TAP_ON,
            selector=str(planned.expression).strip(),
            maestro_tap_id=tap_id,
            maestro_tap_text=tap_text,
        )

    if intent.primary_action is ActionType.INPUT_TEXT:
        literal = quoted_literal_from_step_text(raw_step_text)
        if literal is None or not literal.strip():
            return ExecutionMappingDecision(
                action=SupportedProviderAction.NONE,
                unsupported_reason=(
                    "INPUT_TEXT requires a quoted literal in the scenario step "
                    "(e.g. type 'hello'); refusing to invent input."
                ),
            )
        return ExecutionMappingDecision(
            action=SupportedProviderAction.INPUT_TEXT,
            text_to_input=literal.strip(),
        )

    return ExecutionMappingDecision(
        action=SupportedProviderAction.NONE,
        unsupported_reason=(
            f"ActionType.{intent.primary_action.value} is not supported by the "
            "execution mapping for this planned attempt."
        ),
    )
