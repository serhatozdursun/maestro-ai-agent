"""Apply provider tap/input_text calls to a planned step; honest state transitions."""

from __future__ import annotations

from datetime import UTC, datetime

from maestro_ai_agent.domain.enums import ActionType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.planning import quoted_literal_from_step_text
from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.orchestrator.enums import RunStepPhase, StepValidationStatus
from maestro_ai_agent.orchestrator.execution.action_mapping import (
    ExecutionMappingDecision,
    SupportedProviderAction,
    map_planned_to_provider_action,
)
from maestro_ai_agent.orchestrator.execution.inline_flow_yaml import build_press_key_flow_yaml
from maestro_ai_agent.orchestrator.execution.input_primary_flow_fallback import (
    execute_input_primary_then_flow_fallback,
)
from maestro_ai_agent.orchestrator.execution.runtime_tap_order import runtime_tap_planned_attempts
from maestro_ai_agent.orchestrator.execution.tap_post_effect import (
    next_intent_resolvable_for_branch_probe,
)
from maestro_ai_agent.orchestrator.execution.tap_primary_flow_fallback import (
    execute_tap_primary_then_flow_fallback,
)
from maestro_ai_agent.orchestrator.models import (
    PlannedActionAttempt,
    ProviderExecutionOutcome,
    StepRunState,
)
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import (
    hierarchy_fingerprint,
    hierarchy_meaningfully_changed,
)
from maestro_ai_agent.services.maestro.blocking_popup_dismissal import (
    dismiss_known_blocking_popups_if_present,
)
from maestro_ai_agent.services.maestro.models import ActionResult
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)


def _tap_runtime_attempts(step: StepRunState) -> list[PlannedActionAttempt]:
    assert step.planned_attempt is not None
    if step.ranking is None:
        return [step.planned_attempt]
    attempts = runtime_tap_planned_attempts(
        step.intent,
        step.ranking,
        scenario_step_index=step.scenario_step_index,
    )
    return attempts if attempts else [step.planned_attempt]


def _execute_tap_with_runtime_order(
    screen: MaestroScreenService,
    step: StepRunState,
    *,
    device_id: str | None,
    now: datetime,
    next_intent: StepIntent | None = None,
    tap_resolution: TapResolutionSettings | None = None,
) -> StepRunState:
    attempts = _tap_runtime_attempts(step)
    extra_warnings: list[str] = []
    last_result: ActionResult | None = None
    last_mapping: ExecutionMappingDecision | None = None
    last_provider_action: str = "tap_on"
    base_warnings = list(step.warnings)
    tried_candidate_ids: set[str] = set()

    if step.ranking is not None and step.ranking.ordered:
        log_payload = [
            {
                "candidate_id": e.candidate.candidate_id,
                "expression": e.candidate.expression,
                "score": e.score,
                "structural_kind": e.structural_kind,
            }
            for e in step.ranking.ordered[:15]
        ]
        log.info(
            "scenario_tap_ranked_candidates",
            scenario_step_index=step.scenario_step_index,
            candidates=log_payload,
        )

    for attempt in attempts:
        if attempt.chosen_candidate_id in tried_candidate_ids:
            extra_warnings.append(
                f"runtime_tap_skip_already_tried candidate={attempt.chosen_candidate_id}",
            )
            continue
        mapping = map_planned_to_provider_action(
            step.intent,
            attempt,
            raw_step_text=step.raw_step_text,
            app_id=step.observation.app_id,
        )
        if mapping.action is not SupportedProviderAction.TAP_ON:
            extra_warnings.append(
                f"runtime_tap_skip candidate={attempt.chosen_candidate_id}: "
                f"{mapping.unsupported_reason or 'unsupported'}",
            )
            continue
        assert mapping.selector is not None
        pre_obs = screen.observe_current_screen(
            app_id=step.observation.app_id,
            platform=step.observation.platform,
            device_id=device_id,
            include_screenshot=False,
        )
        log.info(
            "scenario_tap_chosen_candidate",
            scenario_step_index=step.scenario_step_index,
            candidate_id=attempt.chosen_candidate_id,
            expression=mapping.selector,
            selector_type=str(attempt.selector_type),
            score=attempt.score,
        )
        try:
            fb = execute_tap_primary_then_flow_fallback(
                screen,
                app_id=step.observation.app_id,
                platform=step.observation.platform,
                device_id=device_id,
                include_screenshot=False,
                hierarchy_before=pre_obs.hierarchy,
                tap_id=mapping.maestro_tap_id,
                tap_text=mapping.maestro_tap_text,
                selector_type=attempt.selector_type,
                expression=mapping.selector,
                log_event_prefix="scenario_tap",
            )
        except ValueError as exc:
            extra_warnings.append(
                f"runtime_tap_skip candidate={attempt.chosen_candidate_id}: {exc}",
            )
            continue

        provider_action = "run_flow" if fb.run_flow_mcp_args is not None else "tap_on"
        action_res = fb.run_flow_result if fb.run_flow_mcp_args is not None else fb.tap_on_result
        merged = [*base_warnings, *extra_warnings]
        attempted = _with_attempted(
            step.model_copy(update={"warnings": merged}),
            outcome=ProviderExecutionOutcome(
                provider_action=provider_action,
                selector_used=mapping.selector,
                text_input_used=None,
                action_result=None,
                attempted_at=now,
                unsupported_reason=None,
                execution_attempted=True,
            ),
        )
        last_result = action_res
        last_mapping = mapping
        last_provider_action = provider_action
        post_out = fb.post_direct_outcome or "unknown"
        extra_warnings.append(
            f"runtime_tap_try selector={mapping.selector!r} "
            f"terminal_ok={fb.terminal_ok} provider_action={provider_action} "
            f"post_direct_outcome={post_out} "
            f"skipped_run_flow_escalation={fb.skipped_run_flow_escalation}",
        )
        log.info(
            "scenario_tap_post_action_summary",
            scenario_step_index=step.scenario_step_index,
            candidate_id=attempt.chosen_candidate_id,
            terminal_ok=fb.terminal_ok,
            winning_tool=fb.winning_tool,
            post_direct_outcome=post_out,
            skipped_run_flow_escalation=fb.skipped_run_flow_escalation,
        )
        if fb.terminal_ok:
            tr_probe = tap_resolution or TapResolutionSettings()
            wrong_branch = (
                next_intent is not None
                and fb.winning_tool == "tap_on"
                and hierarchy_meaningfully_changed(pre_obs.hierarchy, fb.final_hierarchy)
                and not next_intent_resolvable_for_branch_probe(
                    hierarchy_after=fb.final_hierarchy,
                    next_intent=next_intent,
                    tap_resolution=tr_probe,
                )
            )
            if wrong_branch:
                log.warning(
                    "scenario_tap_wrong_branch",
                    scenario_step_index=step.scenario_step_index,
                    candidate_id=attempt.chosen_candidate_id,
                    effect="state_changed_but_next_step_unresolvable",
                    next_scenario_step_index=next_intent.scenario_step_index,
                )
                extra_warnings.append(
                    "Tap changed the screen but the next scenario step could not be planned "
                    f"on the new hierarchy; attempting back navigation and next ranked candidate "
                    f"(candidate={attempt.chosen_candidate_id}).",
                )
                tried_candidate_ids.add(attempt.chosen_candidate_id)
                back_yaml = build_press_key_flow_yaml(
                    app_id=step.observation.app_id,
                    key="back",
                )
                back_res = screen.run_flow(flow_yaml=back_yaml, device_id=device_id)
                log.info(
                    "scenario_tap_back_navigation",
                    scenario_step_index=step.scenario_step_index,
                    provider_ok=back_res.ok,
                    message=back_res.message,
                )
                post_back = screen.observe_current_screen(
                    app_id=step.observation.app_id,
                    platform=step.observation.platform,
                    device_id=device_id,
                    include_screenshot=False,
                )
                fp_pre = hierarchy_fingerprint(pre_obs.hierarchy)
                fp_back = hierarchy_fingerprint(post_back.hierarchy)
                restored = fp_pre == fp_back
                log.info(
                    "scenario_tap_hierarchy_after_back",
                    scenario_step_index=step.scenario_step_index,
                    fingerprint_restored=restored,
                )
                extra_warnings.append(
                    f"post_back_fingerprint_match_pre_tap={restored}",
                )
                continue

            return _finalize_after_provider(attempted, action_res, now)

        tried_candidate_ids.add(attempt.chosen_candidate_id)
        if fb.skipped_run_flow_escalation:
            extra_warnings.append(
                "Same selector not escalated to run_flow after no UI change; "
                "trying next ranked candidate.",
            )
            log.info(
                "scenario_tap_try_next_candidate",
                scenario_step_index=step.scenario_step_index,
                reason="no_effect_skipped_run_flow_same_selector",
                next_attempt_index=attempt.rank_position + 1,
            )

    if last_result is None:
        reason = "No tap attempts could be mapped to provider tap_on."
        return _unsupported_or_missing(
            step.model_copy(update={"warnings": [*base_warnings, *extra_warnings]}),
            reason,
            now,
        )

    msg = last_result.message or "All runtime tap attempts failed."
    return step.model_copy(
        update={
            "phase": RunStepPhase.EXECUTION_FAILED,
            "validation_status": StepValidationStatus.NOT_APPLICABLE,
            "execution_outcome": ProviderExecutionOutcome(
                provider_action=last_provider_action,
                selector_used=last_mapping.selector if last_mapping else None,
                text_input_used=None,
                action_result=last_result,
                attempted_at=now,
                unsupported_reason=msg,
                execution_attempted=True,
            ),
            "warnings": [*base_warnings, *extra_warnings, msg],
        },
    )


def _execute_dismiss_blocker_step(
    screen: MaestroScreenService,
    step: StepRunState,
    *,
    device_id: str | None,
    now: datetime,
) -> StepRunState:
    """
    Run the same hierarchy-driven blocker registry as preflight, once per scenario step.

    Records ``blocker_episode`` on the step for exploration reports; does not use static
    Continue/OK ``run_flow`` templates.
    """
    assert step.observation is not None
    outcome = dismiss_known_blocking_popups_if_present(
        screen,
        device_id=device_id or "",
        app_id=step.observation.app_id,
        platform=step.observation.platform,
        include_screenshot=False,
    )
    episode = outcome.blocker_episode_dict()
    merged_warnings = [*step.warnings, f"blocker_engine:{outcome.reason}"]

    if outcome.should_abort_run:
        return step.model_copy(
            update={
                "phase": RunStepPhase.EXECUTION_FAILED,
                "validation_status": StepValidationStatus.NOT_APPLICABLE,
                "blocker_episode": episode,
                "execution_outcome": ProviderExecutionOutcome(
                    provider_action="dismiss_blocker_engine",
                    selector_used=None,
                    text_input_used=None,
                    action_result=ActionResult(ok=False, message=outcome.reason),
                    attempted_at=now,
                    unsupported_reason=outcome.reason,
                    execution_attempted=outcome.execution_attempted,
                ),
                "warnings": merged_warnings,
            },
        )

    synthetic = ActionResult(ok=True, message=f"blocker_engine:{outcome.reason}")
    attempted = _with_attempted(
        step.model_copy(update={"warnings": merged_warnings, "blocker_episode": episode}),
        outcome=ProviderExecutionOutcome(
            provider_action="dismiss_blocker_engine",
            selector_used=None,
            text_input_used=None,
            action_result=None,
            attempted_at=now,
            unsupported_reason=None,
            execution_attempted=True,
        ),
    )
    return _finalize_after_provider(attempted, synthetic, now)


def _execute_assert_hierarchy_no_provider(
    step: StepRunState,
    now: datetime,
    mapping: ExecutionMappingDecision,
) -> StepRunState:
    """No MCP call: assert steps are validated on the next hierarchy observation only."""
    base_warnings = list(step.warnings)
    msg = "Hierarchy assert (no provider); post-step validation evaluates visibility."
    selector_audit = mapping.assert_ranked_expression or mapping.assert_surface_literal
    attempted = _with_attempted(
        step.model_copy(update={"warnings": [*base_warnings, msg]}),
        outcome=ProviderExecutionOutcome(
            provider_action="assert_hierarchy",
            selector_used=selector_audit,
            text_input_used=None,
            action_result=None,
            attempted_at=now,
            unsupported_reason=None,
            execution_attempted=True,
        ),
    )
    ok = ActionResult(ok=True, message="assert_hierarchy_no_provider", raw_text=None)
    return _finalize_after_provider(attempted, ok, now)


def classify_skipped_step_for_execute_mode(step: StepRunState) -> StepRunState:
    """
    When selector ranking had no primary, still record honest execution posture.

    - ``INPUT_TEXT`` without a quoted literal → ``MISSING_INPUT_VALUE`` (no invented text).
    - Other non tap/input intents → ``UNSUPPORTED`` (nothing to invoke without a selector).
    - ``TAP`` that lacked hierarchy evidence → leave ``SKIPPED_NO_SELECTOR``.
    - ``INPUT_TEXT`` with a quoted literal is planned for direct ``input_text`` without a
      ranked selector, so this path should not apply; if it does, behavior matches TAP
      (no provider mapping without a planned attempt).
    """
    if step.phase is not RunStepPhase.SKIPPED_NO_SELECTOR:
        return step
    now = datetime.now(UTC)
    action = step.intent.primary_action

    if action is ActionType.INPUT_TEXT:
        literal = quoted_literal_from_step_text(step.raw_step_text)
        if literal is None or not literal.strip():
            return _skipped_to_missing_input(step, now)

    if action is ActionType.SWIPE:
        return _skipped_to_unsupported(
            step,
            now,
            reason=(
                "SWIPE could not be planned: use a plain line such as Swipe left "
                "(or right, up, down), or a quoted targeted line such as "
                "Swipe left on 'Story card' or Swipe 'Story card' left. "
                "Other swipe phrasings are not supported yet."
            ),
        )

    if action not in (
        ActionType.TAP,
        ActionType.INPUT_TEXT,
        ActionType.PRESS_KEY,
        ActionType.SCROLL,
        ActionType.SCROLL_UNTIL_VISIBLE,
        ActionType.DISMISS_BLOCKER,
        ActionType.ASSERT_VISIBLE,
        ActionType.ASSERT_NOT_VISIBLE,
    ):
        return _skipped_to_unsupported(
            step,
            now,
            reason=(
                f"ActionType.{action.value} is not supported by the execution layer "
                "and no primary selector was ranked."
            ),
        )

    return step


def _skipped_to_missing_input(step: StepRunState, now: datetime) -> StepRunState:
    reason = (
        "INPUT_TEXT requires a quoted literal in the scenario step; "
        "refusing to invent input (no selector ranked)."
    )
    return step.model_copy(
        update={
            "phase": RunStepPhase.MISSING_INPUT_VALUE,
            "validation_status": StepValidationStatus.NOT_APPLICABLE,
            "execution_outcome": ProviderExecutionOutcome(
                provider_action=None,
                selector_used=None,
                text_input_used=None,
                action_result=None,
                attempted_at=now,
                unsupported_reason=reason,
                execution_attempted=False,
            ),
            "warnings": [*step.warnings, reason],
        },
    )


def _skipped_to_unsupported(step: StepRunState, now: datetime, *, reason: str) -> StepRunState:
    return step.model_copy(
        update={
            "phase": RunStepPhase.UNSUPPORTED,
            "validation_status": StepValidationStatus.NOT_APPLICABLE,
            "execution_outcome": ProviderExecutionOutcome(
                provider_action=None,
                selector_used=None,
                text_input_used=None,
                action_result=None,
                attempted_at=now,
                unsupported_reason=reason,
                execution_attempted=False,
            ),
            "warnings": [*step.warnings, reason],
        },
    )


class ProviderStepExecutionService:
    """
    Executes supported provider actions for a step already in ``PLANNED``.

    For **TAP**, may try multiple ranked candidates in **runtime order** (text-first,
    then id, relational, point); ranking primary / YAML mapping stay unchanged.

    Does not treat ``ActionResult.ok`` as scenario success—post-action validation is
    required for evidence-based outcomes.
    """

    def __init__(self, screen_service: MaestroScreenService) -> None:
        self._screen = screen_service

    def execute_top_planned_if_supported(
        self,
        step: StepRunState,
        *,
        device_id: str | None,
        next_intent: StepIntent | None = None,
        tap_resolution: TapResolutionSettings | None = None,
    ) -> StepRunState:
        if step.phase is not RunStepPhase.PLANNED or step.planned_attempt is None:
            msg = "execute_top_planned_if_supported requires phase PLANNED and planned_attempt."
            raise ValueError(msg)

        now = datetime.now(UTC)

        if step.intent.primary_action is ActionType.DISMISS_BLOCKER:
            return _execute_dismiss_blocker_step(
                self._screen,
                step,
                device_id=device_id,
                now=now,
            )

        if step.intent.primary_action is ActionType.TAP:
            return _execute_tap_with_runtime_order(
                self._screen,
                step,
                device_id=device_id,
                now=now,
                next_intent=next_intent,
                tap_resolution=tap_resolution,
            )

        planned = step.planned_attempt
        mapping = map_planned_to_provider_action(
            step.intent,
            planned,
            raw_step_text=step.raw_step_text,
            app_id=step.observation.app_id,
        )

        if mapping.action is SupportedProviderAction.NONE:
            return _unsupported_or_missing(step, mapping.unsupported_reason or "Unsupported.", now)

        if mapping.action is SupportedProviderAction.ASSERT_HIERARCHY:
            return _execute_assert_hierarchy_no_provider(step, now, mapping)

        if mapping.action is SupportedProviderAction.RUN_FLOW:
            assert mapping.flow_yaml is not None
            base_warnings = list(step.warnings)
            res = self._screen.run_flow(flow_yaml=mapping.flow_yaml, device_id=device_id)
            extra = "scenario_inline_run_flow executed"
            attempted = _with_attempted(
                step.model_copy(update={"warnings": [*base_warnings, extra]}),
                outcome=ProviderExecutionOutcome(
                    provider_action="run_flow",
                    selector_used=None,
                    text_input_used=None,
                    action_result=None,
                    attempted_at=now,
                    unsupported_reason=None,
                    execution_attempted=True,
                ),
            )
            return _finalize_after_provider(attempted, res, now)

        if mapping.action is SupportedProviderAction.INPUT_TEXT:
            assert mapping.text_to_input is not None
            assert step.observation is not None
            text_val = mapping.text_to_input
            base_warnings = list(step.warnings)
            fb = execute_input_primary_then_flow_fallback(
                self._screen,
                app_id=step.observation.app_id,
                platform=step.observation.platform,
                device_id=device_id,
                include_screenshot=False,
                text=text_val,
                log_event_prefix="scenario_input",
            )
            provider_action = "run_flow" if fb.run_flow_mcp_args is not None else "input_text"
            action_res = (
                fb.run_flow_result if fb.run_flow_mcp_args is not None else fb.input_text_result
            )
            if not fb.terminal_ok and fb.run_flow_mcp_args is None and fb.input_text_result.ok:
                action_res = ActionResult(
                    ok=False,
                    message=(
                        "input_text tool completed but value not reflected in hierarchy; "
                        "run_flow inputText fallback did not run to completion."
                    ),
                    raw_text=None,
                )
            extra = (
                f"scenario_input terminal_ok={fb.terminal_ok} winning_tool={fb.winning_tool!r} "
                f"provider_action={provider_action}"
            )
            attempted = _with_attempted(
                step.model_copy(update={"warnings": [*base_warnings, extra]}),
                outcome=ProviderExecutionOutcome(
                    provider_action=provider_action,
                    selector_used=None,
                    text_input_used=text_val,
                    action_result=None,
                    attempted_at=now,
                    unsupported_reason=None,
                    execution_attempted=True,
                ),
            )
            return _finalize_after_provider(attempted, action_res, now)

        msg = f"Unexpected mapping action: {mapping.action}"
        raise RuntimeError(msg)


def _unsupported_or_missing(step: StepRunState, reason: str, now: datetime) -> StepRunState:
    is_missing_input = step.intent.primary_action is ActionType.INPUT_TEXT and (
        "quoted literal" in reason or "invent" in reason
    )
    phase = RunStepPhase.MISSING_INPUT_VALUE if is_missing_input else RunStepPhase.UNSUPPORTED
    return step.model_copy(
        update={
            "phase": phase,
            "validation_status": StepValidationStatus.NOT_APPLICABLE,
            "execution_outcome": ProviderExecutionOutcome(
                provider_action=None,
                selector_used=None,
                text_input_used=None,
                action_result=None,
                attempted_at=now,
                unsupported_reason=reason,
                execution_attempted=False,
            ),
            "warnings": [*step.warnings, reason],
        },
    )


def _with_attempted(step: StepRunState, *, outcome: ProviderExecutionOutcome) -> StepRunState:
    return step.model_copy(
        update={
            "phase": RunStepPhase.EXECUTION_ATTEMPTED,
            "execution_outcome": outcome,
        },
    )


def _finalize_after_provider(
    step: StepRunState,
    result: ActionResult,
    now: datetime,
) -> StepRunState:
    assert step.execution_outcome is not None
    outcome = step.execution_outcome.model_copy(
        update={"action_result": result, "attempted_at": now},
    )
    if result.ok:
        return step.model_copy(
            update={
                "phase": RunStepPhase.EXECUTED,
                "validation_status": StepValidationStatus.DEFERRED,
                "execution_outcome": outcome,
                "warnings": [
                    *step.warnings,
                    "Provider reported tool success; post-action hierarchy validation runs next.",
                ],
            },
        )
    msg = result.message or "Provider reported failure."
    return step.model_copy(
        update={
            "phase": RunStepPhase.EXECUTION_FAILED,
            "validation_status": StepValidationStatus.NOT_APPLICABLE,
            "execution_outcome": outcome,
            "warnings": [*step.warnings, msg],
        },
    )
