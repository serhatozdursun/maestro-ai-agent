"""Observe → rank → plan for a single step intent (composition, no transport)."""

from __future__ import annotations

from collections.abc import Callable

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.intent_match import infer_target_hints
from maestro_ai_agent.domain.selectors.pipeline import plan_selector_ranking
from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.orchestrator.action_attempt_planning import (
    DIRECT_INPUT_TEXT_CANDIDATE_ID,
    plan_action_attempt_from_ranking,
)
from maestro_ai_agent.orchestrator.models import ObservationCycleResult, StepRunState
from maestro_ai_agent.orchestrator.observation_cycle import build_observation_cycle_result
from maestro_ai_agent.orchestrator.run_state import (
    step_state_after_observation,
    step_state_after_ranking_and_plan,
)
from maestro_ai_agent.orchestrator.visual_advisory_support import (
    build_visual_advisory_request,
    merge_visual_advisory_into_hints,
)
from maestro_ai_agent.services.maestro.models import StructuredScreenObservation
from maestro_ai_agent.services.maestro.visual_target_suggester import VisualTargetSuggester


def observe_screen(
    *,
    observer: Callable[..., StructuredScreenObservation],
    app_id: str,
    platform: Platform,
    device_id: str | None,
    include_screenshot: bool,
) -> ObservationCycleResult:
    structured = observer(
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
    )
    return build_observation_cycle_result(structured)


def rank_and_plan_for_step(
    step: StepRunState,
    *,
    enable_visual_advisory_fallback: bool = False,
    visual_target_suggester: VisualTargetSuggester | None = None,
    tap_resolution: TapResolutionSettings | None = None,
) -> StepRunState:
    """Requires ``step.phase`` at least ``OBSERVED`` and ``step.observation`` set."""
    if step.observation is None:
        msg = "StepRunState.observation is required before rank_and_plan_for_step."
        raise RuntimeError(msg)
    tr = tap_resolution or TapResolutionSettings()
    hints = infer_target_hints(step.intent)
    if tr.prefer_target_kind.strip().lower() != "auto":
        hints = hints.model_copy(
            update={"prefer_structural_kind": tr.prefer_target_kind.strip().lower()},
        )
    ranking = plan_selector_ranking(
        step.observation.hierarchy,
        step.intent,
        hints,
        tap_resolution=tr,
    )
    planned = plan_action_attempt_from_ranking(
        intent=step.intent,
        ranking=ranking,
        scenario_step_index=step.scenario_step_index,
        raw_step_text=step.raw_step_text,
    )
    extra_warnings: list[str] = []
    if enable_visual_advisory_fallback and visual_target_suggester is not None and planned is None:
        obs = step.observation
        shot = obs.screenshot
        if shot is not None and shot.image_bytes:
            try:
                req = build_visual_advisory_request(step, obs)
                advisory = visual_target_suggester.suggest(req)
            except Exception as exc:
                extra_warnings.append(f"Visual advisory suggest() failed: {exc!s}")
                advisory = None
            if advisory is not None:
                hints2 = merge_visual_advisory_into_hints(hints, advisory)
                if hints2.model_dump() != hints.model_dump():
                    ranking = plan_selector_ranking(
                        step.observation.hierarchy,
                        step.intent,
                        hints2,
                        tap_resolution=tr,
                    )
                    planned = plan_action_attempt_from_ranking(
                        intent=step.intent,
                        ranking=ranking,
                        scenario_step_index=step.scenario_step_index,
                        raw_step_text=step.raw_step_text,
                    )
                    extra_warnings.append(
                        "Visual advisory fallback re-ranked with augmented hints "
                        f"(confidence={advisory.confidence:.2f}).",
                    )
                    hints = hints2

    if planned is not None and planned.chosen_candidate_id == DIRECT_INPUT_TEXT_CANDIDATE_ID:
        extra_warnings.append(
            "INPUT_TEXT has no ranked selector; proceeding with direct MCP input_text "
            "using the quoted literal (Maestro: focused field).",
        )

    return step_state_after_ranking_and_plan(
        step,
        ranking=ranking,
        hints=hints,
        planned=planned,
        extra_warnings=extra_warnings,
    )


def run_observe_plan_cycle_for_intent(
    *,
    observer: Callable[..., StructuredScreenObservation],
    app_id: str,
    platform: Platform,
    device_id: str | None,
    include_screenshot: bool,
    intent: StepIntent,
    enable_visual_advisory_fallback: bool = False,
    visual_target_suggester: VisualTargetSuggester | None = None,
    tap_resolution: TapResolutionSettings | None = None,
) -> StepRunState:
    """Full observe → interpret (hints) → rank → choose for one intent."""
    observation = observe_screen(
        observer=observer,
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
    )
    base = StepRunState(
        scenario_step_index=intent.scenario_step_index,
        raw_step_text=intent.raw_step_text,
        intent=intent,
    )
    observed = step_state_after_observation(base, observation)
    return rank_and_plan_for_step(
        observed,
        enable_visual_advisory_fallback=enable_visual_advisory_fallback,
        visual_target_suggester=visual_target_suggester,
        tap_resolution=tap_resolution,
    )
