"""Orchestration: planning-only or observe→plan→execute→validate (hierarchy-based)."""

from __future__ import annotations

from collections.abc import Callable

from maestro_ai_agent.domain.enums import ActionType
from maestro_ai_agent.domain.flow import FlowStep
from maestro_ai_agent.domain.flow_draft import FlowDraftBuilder
from maestro_ai_agent.domain.parse_scenario import parse_scenario_input
from maestro_ai_agent.domain.planning import plan_intents
from maestro_ai_agent.domain.scenario import ParsedScenario
from maestro_ai_agent.orchestrator.decision_log import build_decision_log_entry
from maestro_ai_agent.orchestrator.enums import PlanningRunMode, RunStepPhase
from maestro_ai_agent.orchestrator.execution.execution_service import (
    ProviderStepExecutionService,
    classify_skipped_step_for_execute_mode,
)
from maestro_ai_agent.orchestrator.models import (
    PlannedActionAttempt,
    PlanningOrchestrationResult,
    RunDecisionLogEntry,
    ScenarioRunContext,
    ScenarioRunRequest,
    ScenarioRunState,
    StepRunState,
)
from maestro_ai_agent.orchestrator.run_report import build_run_report
from maestro_ai_agent.orchestrator.step_processing import run_observe_plan_cycle_for_intent
from maestro_ai_agent.orchestrator.validation.validation_service import (
    PostExecutionValidationService,
)
from maestro_ai_agent.scenario.planning_adapter import build_parsed_scenario_from_canonical
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text
from maestro_ai_agent.services.maestro.models import StructuredScreenObservation
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.services.maestro.visual_target_suggester import VisualTargetSuggester

_HARD_STOP_PHASES: frozenset[RunStepPhase] = frozenset(
    {
        RunStepPhase.EXECUTION_FAILED,
        RunStepPhase.MISSING_INPUT_VALUE,
        RunStepPhase.UNSUPPORTED,
        RunStepPhase.VALIDATION_FAILED,
    },
)


def _step_is_hard_failure(step: StepRunState) -> bool:
    return step.phase in _HARD_STOP_PHASES


def _resolve_parsed(request: ScenarioRunRequest) -> ParsedScenario:
    if request.parsed_scenario is not None:
        return request.parsed_scenario
    assert request.scenario_input is not None
    inp = request.scenario_input
    if request.use_canonical_scenario_normalization:
        norm = normalize_scenario_text(
            inp.scenario_text,
            enable_ai_fallback=False,
            ai_fallback=None,
        )
        parsed = build_parsed_scenario_from_canonical(
            norm.canonical,
            app_id=inp.app_id,
            platform=inp.platform,
            title=inp.title,
        )
        merged_warnings = [*parsed.warnings, *norm.warnings]
        return parsed.model_copy(update={"warnings": merged_warnings})
    return parse_scenario_input(inp)


def _resolved_flow_target_hint(step: StepRunState, p: PlannedActionAttempt) -> str | None:
    """Prefer hierarchy-resolved dismiss selector for draft preview after execution."""
    if step.intent.primary_action is ActionType.DISMISS_BLOCKER and step.blocker_episode:
        ep = step.blocker_episode
        basis = (ep.get("selector_basis") or "").strip().lower()
        if basis == "id" and (ep.get("dismiss_id") or "").strip():
            return f"id:{ep['dismiss_id'].strip()}"
        if basis == "text" and (ep.get("dismiss_text") or "").strip():
            return f"text:{ep['dismiss_text'].strip()}"
        da = ep.get("dismiss_action")
        if isinstance(da, dict):
            expr = (da.get("expression") or "").strip()
            if expr:
                return expr
    return p.expression


def _flow_step_from_planned_state(step: StepRunState) -> FlowStep | None:
    if step.phase != RunStepPhase.PLANNED or step.planned_attempt is None:
        return None
    p = step.planned_attempt
    return FlowStep(
        sequence=0,
        action=p.action,
        summary=f"[planned] {step.intent.goal_summary}",
        target_selector_hint=p.expression,
        intent_id=p.intent_id,
        metadata={
            "scenario_step_index": str(step.scenario_step_index),
            "candidate_id": p.chosen_candidate_id,
        },
    )


def _build_post_execution_flow_step(step: StepRunState) -> FlowStep | None:
    ex = step.execution_outcome
    if ex is None or ex.action_result is None or not ex.action_result.ok:
        return None
    p = step.planned_attempt
    if p is None or step.post_action_validation is None:
        return None
    val = step.post_action_validation
    hint = _resolved_flow_target_hint(step, p)
    return FlowStep(
        sequence=0,
        action=p.action,
        summary=f"[executed] {step.intent.goal_summary}",
        target_selector_hint=hint,
        input_value=ex.text_input_used,
        intent_id=p.intent_id,
        metadata={
            "scenario_step_index": str(step.scenario_step_index),
            "candidate_id": p.chosen_candidate_id,
            "provider_action": ex.provider_action or "",
            "validation_outcome": val.outcome.value,
        },
    )


def _append_post_execution_to_draft(builder: FlowDraftBuilder, step: StepRunState) -> None:
    flow = _build_post_execution_flow_step(step)
    if flow is None:
        return
    flow = flow.model_copy(update={"sequence": builder.step_count})
    if step.phase is RunStepPhase.VALIDATED:
        builder.append_executed_validated(flow)
    elif step.phase is RunStepPhase.VALIDATION_FAILED:
        builder.append_executed_validation_failed(flow)
    elif step.phase is RunStepPhase.VALIDATION_INCONCLUSIVE:
        builder.append_executed_validation_inconclusive(flow)
    elif step.phase is RunStepPhase.VALIDATION_SKIPPED:
        builder.append_executed_validation_skipped(flow)


class ScenarioPlanningOrchestrator:
    """
    Agent loop: observe → rank → plan; optional execute (tap / input_text) + hierarchy validation.

    Injects :class:`MaestroScreenService` (observe + forward tap/input to the same provider).

    Optional :class:`VisualTargetSuggester` is advisory only: used for a second deterministic
    ranking pass when ``ScenarioRunRequest.enable_visual_advisory_fallback`` is true.
    """

    def __init__(
        self,
        screen_service: MaestroScreenService,
        *,
        visual_target_suggester: VisualTargetSuggester | None = None,
    ) -> None:
        self._screen = screen_service
        self._visual_target_suggester = visual_target_suggester

    def run_planning_only(
        self,
        request: ScenarioRunRequest,
        *,
        draft_builder: FlowDraftBuilder | None = None,
    ) -> PlanningOrchestrationResult:
        if request.planning_mode != PlanningRunMode.PLANNING_ONLY:
            msg = f"Expected {PlanningRunMode.PLANNING_ONLY}, got {request.planning_mode!r}."
            raise ValueError(msg)
        return self._run(request, execute=False, draft_builder=draft_builder)

    def run_observe_plan_execute(
        self,
        request: ScenarioRunRequest,
        *,
        draft_builder: FlowDraftBuilder | None = None,
    ) -> PlanningOrchestrationResult:
        """Observe, rank, plan, execute when mapped, then re-observe for lightweight validation."""
        if request.planning_mode != PlanningRunMode.OBSERVE_PLAN_EXECUTE:
            msg = f"Expected {PlanningRunMode.OBSERVE_PLAN_EXECUTE}, got {request.planning_mode!r}."
            raise ValueError(msg)
        return self._run(request, execute=True, draft_builder=draft_builder)

    def _run(
        self,
        request: ScenarioRunRequest,
        *,
        execute: bool,
        draft_builder: FlowDraftBuilder | None,
    ) -> PlanningOrchestrationResult:
        parsed = _resolve_parsed(request)
        intents = plan_intents(parsed)
        builder = draft_builder or FlowDraftBuilder(run_label=request.run_label)

        ctx = ScenarioRunContext(
            device_id=request.device_id,
            planning_mode=request.planning_mode,
        )
        app_id = parsed.input.app_id
        platform = parsed.input.platform

        observer: Callable[..., StructuredScreenObservation] = self._screen.observe_current_screen
        executor = ProviderStepExecutionService(self._screen) if execute else None
        validator = PostExecutionValidationService(self._screen) if execute else None

        step_states: list[StepRunState] = []
        decision_log: list[RunDecisionLogEntry] = []

        intents_to_run = list(intents)
        if request.max_steps is not None:
            intents_to_run = intents_to_run[: request.max_steps]

        stopped_after_first = False
        suggester = (
            self._visual_target_suggester if request.enable_visual_advisory_fallback else None
        )
        for idx, intent in enumerate(intents_to_run):
            step = run_observe_plan_cycle_for_intent(
                observer=observer,
                app_id=app_id,
                platform=platform,
                device_id=request.device_id,
                include_screenshot=request.include_screenshot,
                intent=intent,
                enable_visual_advisory_fallback=request.enable_visual_advisory_fallback,
                visual_target_suggester=suggester,
                tap_resolution=request.tap_resolution,
            )
            next_intent = intents_to_run[idx + 1] if idx + 1 < len(intents_to_run) else None
            if executor is not None:
                if step.phase is RunStepPhase.PLANNED:
                    step = executor.execute_top_planned_if_supported(
                        step,
                        device_id=request.device_id,
                        next_intent=next_intent,
                        tap_resolution=request.tap_resolution,
                    )
                elif step.phase is RunStepPhase.SKIPPED_NO_SELECTOR:
                    step = classify_skipped_step_for_execute_mode(step)
            if validator is not None and step.phase is RunStepPhase.EXECUTED:
                step = validator.validate_after_provider_success(
                    step,
                    app_id=app_id,
                    platform=platform,
                    device_id=request.device_id,
                    include_screenshot=request.include_screenshot,
                )
            step_states.append(step)
            entry = build_decision_log_entry(
                step,
                planning_only=not execute,
                planning_mode=request.planning_mode,
                tap_resolution=request.tap_resolution,
            )
            decision_log.append(entry)

            if execute:
                _append_post_execution_to_draft(builder, step)
            else:
                planned_flow = _flow_step_from_planned_state(step)
                if planned_flow is not None:
                    flow = planned_flow.model_copy(update={"sequence": builder.step_count})
                    builder.append_planned(flow)

            if request.stop_after_first_planned and step.planned_attempt is not None:
                stopped_after_first = True
                break

            if request.stop_on_first_hard_failure and _step_is_hard_failure(step):
                break

        max_steps_applied = bool(
            request.max_steps is not None and len(intents) > request.max_steps,
        )

        state = ScenarioRunState(
            context=ctx,
            request=request,
            step_states=step_states,
            flow_draft=builder.draft(),
        )
        report = build_run_report(
            run_id=ctx.run_id,
            planning_mode=request.planning_mode,
            decision_log=decision_log,
            stopped_after_first=stopped_after_first,
            max_steps_applied=max_steps_applied,
        )
        return PlanningOrchestrationResult(state=state, report=report)
