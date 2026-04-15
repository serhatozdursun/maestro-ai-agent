"""
Conservative dismissal of in-app blocking dialogs (not OS permission sheets).

Uses the same hierarchy observation path as the rest of the stack. Only explicit,
registry-driven patterns are handled—no generic auto-dismiss.

Dismissal uses the shared tap strategy: direct ``tap_on`` then ``run_flow`` when ineffective,
with ``blocker_popup_fast_fallback`` (very short settle when the tap succeeds, no settle when
the provider fails, first post-tap hierarchy read without screenshot for speed, immediate
``run_flow`` when the primary tap is ineffective).

**Invocation policy:**

- **Preflight (unchanged):** ``dismiss_known_blocking_popups_if_present`` runs **once**
  after launch + hierarchy stability.
- **Scenario step:** ``ActionType.DISMISS_BLOCKER`` runs the **same** engine once in
  ``ProviderStepExecutionService`` (after planning), using the step's pre-action
  hierarchy context—**no** automatic sweeps after other intents or on generic
  "stuck" heuristics (keeps behavior bounded).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maestro_ai_agent.domain.dialog_signals import (
    collect_allowlist_dismiss_nodes,
    text_substring_present,
)
from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.runtime_blockers import (
    BlockerDismissAction,
    BlockerPattern,
    default_runtime_blocker_patterns,
)
from maestro_ai_agent.orchestrator.execution.tap_primary_flow_fallback import (
    execute_tap_primary_then_flow_fallback,
)
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import visible_text_tokens
from maestro_ai_agent.services.maestro.mcp_adapter import tap_on_selector_basis
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)

PATTERN_DEVELOPER_MODE_CONTINUE = "developer_mode_continue"


def _dismiss_action_to_dict(action: BlockerDismissAction) -> dict[str, Any]:
    return {
        "tap_text": action.tap_text,
        "tap_id": action.tap_id,
        "selector_basis": action.selector_basis,
        "expression": action.expression,
        "choice_reason": action.choice_reason,
        "selector_type": action.selector_type.value,
    }


def _dismiss_tap_targets_from_mcp_args(
    tap_args: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    """``(text, id)`` strings suitable for YAML / logs from a ``tap_on`` MCP argument dict."""
    if not tap_args:
        return None, None
    raw_txt = tap_args.get("text")
    raw_id = tap_args.get("id")
    text = raw_txt.strip() if isinstance(raw_txt, str) and raw_txt.strip() else None
    rid = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None
    return text, rid


@dataclass(frozen=True)
class KnownBlockingPopupOutcome:
    """Outcome of a preflight runtime blocker pass (one pattern at most)."""

    handled: bool

    pattern_id: str | None
    """Identifier of the matched pattern, if any."""

    reason: str
    """Machine-oriented outcome code / message for logs and artifacts."""

    should_abort_run: bool = False
    """If True, scenario-run must not continue into the main scenario (blocker unresolved)."""

    popup_tool_name: str | None = None
    """Maestro MCP tool that produced the last provider attempt (``tap_on`` or ``run_flow``)."""

    popup_tool_args: dict[str, Any] | None = None
    """Exact arguments dict passed to MCP for that tool (serializable)."""

    tap_selector_basis: str | None = None
    """For ``tap_on``: ``text`` or ``id``; ``none`` when only ``run_flow`` was used."""

    dismiss_tap_text: str | None = None
    """Literal used for MCP ``tap_on`` ``text`` when dismissing (for YAML export)."""

    dismiss_tap_id: str | None = None
    """Literal used for MCP ``tap_on`` ``id`` when dismissing (for YAML export)."""

    dismiss_choice_reason: str | None = None
    """Deterministic audit string from hierarchy-based dismiss selection."""

    detected: bool = False
    """True when a registry or early developer-mode blocker **signal** was present."""

    dismiss_action_resolved: dict[str, Any] | None = None
    """Serialized :class:`BlockerDismissAction` chosen before execution, if any."""

    execution_attempted: bool = False
    """True after a dismiss tap / ``run_flow`` fallback chain was attempted."""

    execution_ok: bool | None = None
    """Provider chain terminal_ok when ``execution_attempted``; else None."""

    verified_cleared: bool | None = None
    """Pattern ``verify_cleared`` after a successful provider chain; else None."""

    def blocker_episode_dict(self) -> dict[str, Any]:
        """Structured episode for exploration reports and per-step audit."""
        return {
            "pattern_id": self.pattern_id,
            "detected": self.detected,
            "dismiss_action": self.dismiss_action_resolved,
            "execution_attempted": self.execution_attempted,
            "execution_result": (
                {"ok": self.execution_ok, "code": self.reason} if self.execution_attempted else None
            ),
            "verified_cleared": self.verified_cleared,
            "abort_reason": self.reason if self.should_abort_run else None,
            "selector_basis": self.tap_selector_basis,
            "dismiss_text": self.dismiss_tap_text,
            "dismiss_id": self.dismiss_tap_id,
            "dismiss_choice_reason": self.dismiss_choice_reason,
            "handled": self.handled,
            "should_abort_run": self.should_abort_run,
            "code": self.reason,
        }


def _outcome_no_pattern() -> KnownBlockingPopupOutcome:
    return KnownBlockingPopupOutcome(
        handled=False,
        pattern_id=None,
        reason="no_known_blocking_pattern",
        detected=False,
        dismiss_action_resolved=None,
        execution_attempted=False,
        execution_ok=None,
        verified_cleared=None,
    )


def _outcome_developer_mode_no_allowlist_dismiss(
    *,
    sample_tokens: list[str],
) -> KnownBlockingPopupOutcome:
    log.warning(
        "popup_detected",
        pattern=PATTERN_DEVELOPER_MODE_CONTINUE,
        dismissible=False,
        reason="developer_mode_without_allowlist_dismiss",
        visible_tokens_sample=sample_tokens,
    )
    return KnownBlockingPopupOutcome(
        handled=False,
        pattern_id=PATTERN_DEVELOPER_MODE_CONTINUE,
        reason="developer_mode_seen_but_allowlist_dismiss_not_found",
        should_abort_run=False,
        detected=True,
        dismiss_action_resolved=None,
        execution_attempted=False,
        execution_ok=None,
        verified_cleared=None,
    )


def dismiss_known_blocking_popups_if_present(
    screen: MaestroScreenService,
    *,
    device_id: str,
    app_id: str,
    platform: Platform,
    include_screenshot: bool,
    patterns: list[BlockerPattern] | None = None,
) -> KnownBlockingPopupOutcome:
    """
    Observe once; if a registry pattern matches, resolve a hierarchy-derived dismiss tap,
    run tap primary + ``run_flow`` fallback, then verify with the pattern's clearance rule.
    """
    registry = patterns if patterns is not None else default_runtime_blocker_patterns()

    obs = screen.observe_current_screen(
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
    )
    hierarchy = obs.hierarchy

    if text_substring_present(hierarchy, "developer mode") and not collect_allowlist_dismiss_nodes(
        hierarchy,
    ):
        sample = sorted(visible_text_tokens(hierarchy))[:12]
        return _outcome_developer_mode_no_allowlist_dismiss(sample_tokens=sample)

    matched: tuple[BlockerPattern, BlockerDismissAction] | None = None
    for pattern in registry:
        if not pattern.detect(hierarchy):
            continue
        action = pattern.resolve_dismiss(hierarchy)
        if action is None:
            log.warning(
                "popup_detected",
                pattern=pattern.pattern_id,
                dismissible=False,
                reason="blocker_detected_dismiss_unresolved",
            )
            return KnownBlockingPopupOutcome(
                handled=False,
                pattern_id=pattern.pattern_id,
                reason="blocker_detected_dismiss_unresolved",
                should_abort_run=True,
                detected=True,
                dismiss_action_resolved=None,
                execution_attempted=False,
                execution_ok=None,
                verified_cleared=None,
            )
        matched = (pattern, action)
        break

    if matched is None:
        log.info(
            "popup_not_found",
            pattern=None,
            reason="no_known_blocking_pattern",
        )
        return _outcome_no_pattern()

    pattern, action = matched
    resolved_dict = _dismiss_action_to_dict(action)
    log.info(
        "popup_detected",
        pattern=pattern.pattern_id,
        dismissible=True,
        tap_basis=action.selector_basis,
        tap_text=action.tap_text,
        tap_id=action.tap_id,
        choice_reason=action.choice_reason,
    )

    res = execute_tap_primary_then_flow_fallback(
        screen,
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
        hierarchy_before=hierarchy,
        tap_id=action.tap_id,
        tap_text=action.tap_text,
        selector_type=action.selector_type,
        expression=action.expression,
        log_event_prefix="popup",
        blocker_popup_fast_fallback=True,
    )

    tool_name = res.winning_tool or ("run_flow" if res.run_flow_result is not None else "tap_on")
    tool_args: dict[str, Any] | None = res.run_flow_mcp_args or res.tap_on_mcp_args
    basis = tap_on_selector_basis(res.tap_on_mcp_args or {}) if res.tap_on_mcp_args else None
    d_txt, d_id = _dismiss_tap_targets_from_mcp_args(res.tap_on_mcp_args)

    if not res.terminal_ok:
        log.info(
            "popup_blocking_failure",
            pattern=pattern.pattern_id,
            stage="tap_primary_flow_fallback",
            provider_ok=False,
            winning_tool=res.winning_tool,
        )
        return KnownBlockingPopupOutcome(
            handled=False,
            pattern_id=pattern.pattern_id,
            reason="tap_primary_flow_fallback_failed",
            should_abort_run=True,
            popup_tool_name=tool_name,
            popup_tool_args=dict(tool_args) if tool_args else None,
            tap_selector_basis=basis,
            dismiss_tap_text=d_txt,
            dismiss_tap_id=d_id,
            dismiss_choice_reason=action.choice_reason,
            detected=True,
            dismiss_action_resolved=resolved_dict,
            execution_attempted=True,
            execution_ok=False,
            verified_cleared=None,
        )

    if not pattern.verify_cleared(res.final_hierarchy):
        log.info(
            "popup_dismiss_verification_failed",
            pattern=pattern.pattern_id,
            reason="blocker_pattern_still_detected_after_tap",
        )
        log.info(
            "popup_blocking_failure",
            pattern=pattern.pattern_id,
            stage="post_action_hierarchy",
            provider_ok=True,
        )
        return KnownBlockingPopupOutcome(
            handled=False,
            pattern_id=pattern.pattern_id,
            reason="blocker_still_detected_after_dismiss",
            should_abort_run=True,
            popup_tool_name=tool_name,
            popup_tool_args=dict(tool_args) if tool_args else None,
            tap_selector_basis=basis,
            dismiss_tap_text=d_txt,
            dismiss_tap_id=d_id,
            dismiss_choice_reason=action.choice_reason,
            detected=True,
            dismiss_action_resolved=resolved_dict,
            execution_attempted=True,
            execution_ok=True,
            verified_cleared=False,
        )

    log.info(
        "popup_dismiss_verification_passed",
        pattern=pattern.pattern_id,
        tap_selector_basis=basis,
        dismiss_tap_text=d_txt,
        dismiss_tap_id=d_id,
    )
    return KnownBlockingPopupOutcome(
        handled=True,
        pattern_id=pattern.pattern_id,
        reason="dismissed_blocker_via_tap_primary_flow_then_verified",
        should_abort_run=False,
        popup_tool_name=tool_name,
        popup_tool_args=dict(tool_args) if tool_args else None,
        tap_selector_basis=basis,
        dismiss_tap_text=d_txt,
        dismiss_tap_id=d_id,
        dismiss_choice_reason=action.choice_reason,
        detected=True,
        dismiss_action_resolved=resolved_dict,
        execution_attempted=True,
        execution_ok=True,
        verified_cleared=True,
    )
