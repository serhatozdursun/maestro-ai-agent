"""
Tap execution: direct MCP ``tap_on`` first, then ``run_flow`` with a minimal one-tap YAML.

Used by scenario step execution and by known in-app blocking dialog dismissal so behavior
stays consistent when Maestro accepts ``tap_on`` but the UI does not update until a flow run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from maestro_ai_agent.app.maestro_draft_preview import build_minimal_single_tap_flow_yaml
from maestro_ai_agent.domain.dialog_signals import developer_mode_continue_dialog_visible
from maestro_ai_agent.domain.enums import Platform, SelectorType
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.orchestrator.execution.tap_post_effect import (
    PostTapUiOutcome,
    classify_post_direct_tap,
)
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    hierarchy_meaningfully_changed,
)
from maestro_ai_agent.services.maestro.mcp_adapter import (
    run_flow_mcp_arguments,
    tap_on_mcp_arguments,
)
from maestro_ai_agent.services.maestro.models import ActionResult
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)

# Blocker / known-popup dismissal only: brief yield before hierarchy read so the UI can
# advance one frame; kept tiny so ``run_flow`` fallback is not delayed by a long settle.
BLOCKER_POPUP_POST_TAP_SETTLE_S = 0.05


def first_direct_tap_ineffective(
    *,
    before: HierarchySnapshot,
    after: HierarchySnapshot,
    tap_result: ActionResult,
) -> bool:
    """
    True when a follow-up strategy should run: provider failure, blocking dialog still up,
    or hierarchy unchanged after a nominally successful ``tap_on``.
    """
    if not tap_result.ok:
        return True
    if developer_mode_continue_dialog_visible(after):
        return True
    return not hierarchy_meaningfully_changed(before, after)


@dataclass(frozen=True)
class TapPrimaryFlowFallbackResult:
    """Outcome of ``tap_on`` and optional ``run_flow`` after the last hierarchy read."""

    terminal_ok: bool
    winning_tool: str | None
    tap_on_result: ActionResult
    run_flow_result: ActionResult | None
    flow_yaml: str | None
    tap_on_mcp_args: dict[str, Any] | None
    run_flow_mcp_args: dict[str, Any] | None
    final_hierarchy: HierarchySnapshot
    # PostTapUiOutcome after tap_on; skipped_run_flow_escalation avoids
    # same-selector run_flow.
    post_direct_outcome: str | None = None
    skipped_run_flow_escalation: bool = False


def execute_tap_primary_then_flow_fallback(
    screen: MaestroScreenService,
    *,
    app_id: str,
    platform: Platform,
    device_id: str | None,
    include_screenshot: bool,
    hierarchy_before: HierarchySnapshot,
    tap_id: str | None,
    tap_text: str | None,
    selector_type: SelectorType,
    expression: str,
    log_event_prefix: str = "tap_exec",
    blocker_popup_fast_fallback: bool = False,
) -> TapPrimaryFlowFallbackResult:
    """
    Run ``tap_on`` then, if ineffective, ``run_flow`` with YAML from selector + expression.

    ``expression`` must match the ranked selector string (e.g. ``text:Cart``, ``id:bag``).

    When ``blocker_popup_fast_fallback`` is True (runtime blocker / known-popup dismissal only):
    apply a very short post-tap settle, skip screenshot on the first post-tap hierarchy read for
    speed, and log that ``run_flow`` is started immediately after an ineffective primary tap.
    Scenario taps keep the default (``False``).
    """
    tap_args = tap_on_mcp_arguments(tap_id=tap_id, tap_text=tap_text, device_id=device_id)
    if "id" not in tap_args and "text" not in tap_args:
        msg = "Primary tap requires non-empty tap_id or tap_text for tap_on."
        raise ValueError(msg)

    basis = "id" if "id" in tap_args else "text"
    log.info(
        f"{log_event_prefix}_primary_tool_call",
        tool_name="tap_on",
        args=tap_args,
        tap_selector_basis=basis,
        blocker_popup_fast_fallback=blocker_popup_fast_fallback,
    )
    tap_res = screen.tap_on(tap_id=tap_id, tap_text=tap_text, device_id=device_id)
    log.info(
        f"{log_event_prefix}_primary_tap_returned",
        provider_ok=tap_res.ok,
        blocker_popup_fast_fallback=blocker_popup_fast_fallback,
    )
    if blocker_popup_fast_fallback and tap_res.ok:
        time.sleep(BLOCKER_POPUP_POST_TAP_SETTLE_S)
        log.info(
            f"{log_event_prefix}_primary_post_tap_settle_complete",
            settle_s=BLOCKER_POPUP_POST_TAP_SETTLE_S,
        )
    elif blocker_popup_fast_fallback and not tap_res.ok:
        log.info(
            f"{log_event_prefix}_primary_post_tap_settle_skipped",
            reason="tap_provider_failed_immediate_hierarchy_read",
        )
    post1 = screen.observe_current_screen(
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=False if blocker_popup_fast_fallback else include_screenshot,
    )
    after1 = post1.hierarchy
    direct_outcome = classify_post_direct_tap(
        hierarchy_before=hierarchy_before,
        hierarchy_after=after1,
        tap_result=tap_res,
    )
    if not first_direct_tap_ineffective(before=hierarchy_before, after=after1, tap_result=tap_res):
        log.info(
            f"{log_event_prefix}_primary_effective",
            tool_name="tap_on",
            provider_ok=tap_res.ok,
            post_direct_outcome=direct_outcome.value,
        )
        return TapPrimaryFlowFallbackResult(
            terminal_ok=tap_res.ok,
            winning_tool="tap_on" if tap_res.ok else None,
            tap_on_result=tap_res,
            run_flow_result=None,
            flow_yaml=None,
            tap_on_mcp_args=dict(tap_args),
            run_flow_mcp_args=None,
            final_hierarchy=after1,
            post_direct_outcome=direct_outcome.value,
            skipped_run_flow_escalation=False,
        )

    log.info(
        f"{log_event_prefix}_primary_ineffective",
        tool_name="tap_on",
        provider_ok=tap_res.ok,
        post_direct_outcome=direct_outcome.value,
        will_attempt_run_flow=True,
        blocker_popup_fast_fallback=blocker_popup_fast_fallback,
    )

    # Scenario taps: do not re-hit the same selector via run_flow when tap succeeded but UI
    # did not change (rotation should try the next ranked candidate instead).
    if not blocker_popup_fast_fallback and direct_outcome is PostTapUiOutcome.NO_EFFECT:
        log.info(
            f"{log_event_prefix}_run_flow_skipped",
            reason="scenario_no_ui_change_after_ok_tap_try_next_ranked_candidate",
            post_direct_outcome=direct_outcome.value,
        )
        return TapPrimaryFlowFallbackResult(
            terminal_ok=False,
            winning_tool=None,
            tap_on_result=tap_res,
            run_flow_result=None,
            flow_yaml=None,
            tap_on_mcp_args=dict(tap_args),
            run_flow_mcp_args=None,
            final_hierarchy=after1,
            post_direct_outcome=direct_outcome.value,
            skipped_run_flow_escalation=True,
        )

    if blocker_popup_fast_fallback:
        log.info(
            f"{log_event_prefix}_fallback_run_flow_started_immediately",
            reason="blocker_popup_fast_fallback_after_ineffective_primary_tap",
        )
    try:
        flow_yaml = build_minimal_single_tap_flow_yaml(
            app_id=app_id,
            selector_type=selector_type,
            expression=expression,
        )
    except ValueError as exc:
        log.warning(f"{log_event_prefix}_run_flow_skipped", reason=str(exc))
        return TapPrimaryFlowFallbackResult(
            terminal_ok=False,
            winning_tool=None,
            tap_on_result=tap_res,
            run_flow_result=None,
            flow_yaml=None,
            tap_on_mcp_args=dict(tap_args),
            run_flow_mcp_args=None,
            final_hierarchy=after1,
            post_direct_outcome=direct_outcome.value,
            skipped_run_flow_escalation=False,
        )

    rf_args = run_flow_mcp_arguments(flow_yaml=flow_yaml, device_id=device_id)
    log.info(
        f"{log_event_prefix}_run_flow_tool_call",
        tool_name="run_flow",
        args=rf_args,
    )
    rf_res = screen.run_flow(flow_yaml=flow_yaml, device_id=device_id)
    post2 = screen.observe_current_screen(
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
    )
    log.info(
        f"{log_event_prefix}_run_flow_finished",
        provider_ok=rf_res.ok,
        message=rf_res.message,
    )
    return TapPrimaryFlowFallbackResult(
        terminal_ok=rf_res.ok,
        winning_tool="run_flow" if rf_res.ok else None,
        tap_on_result=tap_res,
        run_flow_result=rf_res,
        flow_yaml=flow_yaml,
        tap_on_mcp_args=dict(tap_args),
        run_flow_mcp_args=dict(rf_args),
        final_hierarchy=post2.hierarchy,
        post_direct_outcome=direct_outcome.value,
        skipped_run_flow_escalation=False,
    )
