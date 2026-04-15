"""
Input execution: direct MCP ``input_text`` first, then ``run_flow`` with minimal ``inputText`` YAML.

Mirrors :mod:`tap_primary_flow_fallback` so Maestro can accept ``input_text`` while the UI does not
reflect the value until a flow document runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maestro_ai_agent.app.maestro_draft_preview import build_minimal_input_text_flow_yaml
from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    input_literal_reflected_in_hierarchy,
)
from maestro_ai_agent.services.maestro.mcp_adapter import (
    input_text_mcp_arguments,
    run_flow_mcp_arguments,
)
from maestro_ai_agent.services.maestro.models import ActionResult
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)


def first_direct_input_ineffective(
    *,
    after: HierarchySnapshot,
    input_result: ActionResult,
    text: str,
) -> bool:
    """
    True when ``run_flow`` should be attempted after ``input_text``.

    Ineffective means provider failure, or success without **input-targeted** reflection
    (same conservative rules as post-action validation — not plain substring on all nodes).
    """
    return not input_result.ok or not input_literal_reflected_in_hierarchy(after, text)


@dataclass(frozen=True)
class InputPrimaryFlowFallbackResult:
    """Outcome of ``input_text`` plus optional ``run_flow`` (hierarchy after the last action)."""

    terminal_ok: bool
    winning_tool: str | None
    input_text_result: ActionResult
    run_flow_result: ActionResult | None
    flow_yaml: str | None
    input_text_mcp_args: dict[str, Any] | None
    run_flow_mcp_args: dict[str, Any] | None
    final_hierarchy: HierarchySnapshot


def execute_input_primary_then_flow_fallback(
    screen: MaestroScreenService,
    *,
    app_id: str,
    platform: Platform,
    device_id: str | None,
    include_screenshot: bool,
    text: str,
    log_event_prefix: str = "input_exec",
) -> InputPrimaryFlowFallbackResult:
    """
    Run ``input_text`` then, if the post hierarchy does not reflect ``text``, ``run_flow`` YAML.
    """
    stripped = (text or "").strip()
    if not stripped:
        msg = "input_text requires non-empty text."
        raise ValueError(msg)

    log.info(
        f"{log_event_prefix}_primary_tool_call",
        tool_name="input_text",
        text_len=len(stripped),
    )
    in_args = input_text_mcp_arguments(text=stripped, device_id=device_id)
    in_res = screen.input_text(text=stripped, device_id=device_id)
    post1 = screen.observe_current_screen(
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
    )
    after1 = post1.hierarchy
    if not first_direct_input_ineffective(after=after1, input_result=in_res, text=stripped):
        log.info(
            f"{log_event_prefix}_primary_effective",
            tool_name="input_text",
            provider_ok=in_res.ok,
        )
        return InputPrimaryFlowFallbackResult(
            terminal_ok=in_res.ok,
            winning_tool="input_text" if in_res.ok else None,
            input_text_result=in_res,
            run_flow_result=None,
            flow_yaml=None,
            input_text_mcp_args=dict(in_args),
            run_flow_mcp_args=None,
            final_hierarchy=after1,
        )

    log.info(
        f"{log_event_prefix}_primary_ineffective",
        tool_name="input_text",
        provider_ok=in_res.ok,
        will_attempt_run_flow=True,
    )
    try:
        flow_yaml = build_minimal_input_text_flow_yaml(app_id=app_id, text=stripped)
    except ValueError as exc:
        log.warning(f"{log_event_prefix}_run_flow_skipped", reason=str(exc))
        return InputPrimaryFlowFallbackResult(
            terminal_ok=False,
            winning_tool=None,
            input_text_result=in_res,
            run_flow_result=None,
            flow_yaml=None,
            input_text_mcp_args=dict(in_args),
            run_flow_mcp_args=None,
            final_hierarchy=after1,
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
    return InputPrimaryFlowFallbackResult(
        terminal_ok=rf_res.ok,
        winning_tool="run_flow" if rf_res.ok else None,
        input_text_result=in_res,
        run_flow_result=rf_res,
        flow_yaml=flow_yaml,
        input_text_mcp_args=dict(in_args),
        run_flow_mcp_args=dict(rf_args),
        final_hierarchy=post2.hierarchy,
    )
