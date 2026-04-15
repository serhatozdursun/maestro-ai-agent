"""Pure transitions for orchestrator run / step state (no I/O)."""

from __future__ import annotations

from maestro_ai_agent.domain.selectors.ranking_types import SelectorRankingResult
from maestro_ai_agent.domain.selectors.target_hints import TargetHints
from maestro_ai_agent.orchestrator.enums import RunStepPhase
from maestro_ai_agent.orchestrator.models import (
    ObservationCycleResult,
    PlannedActionAttempt,
    StepRunState,
)


def step_state_after_observation(
    step: StepRunState,
    observation: ObservationCycleResult,
) -> StepRunState:
    return step.model_copy(
        update={
            "phase": RunStepPhase.OBSERVED,
            "observation": observation,
        },
    )


def step_state_after_ranking_and_plan(
    step: StepRunState,
    *,
    ranking: SelectorRankingResult,
    hints: TargetHints,
    planned: PlannedActionAttempt | None,
    extra_warnings: list[str] | None = None,
) -> StepRunState:
    warnings = [*step.warnings, *(extra_warnings or [])]
    if planned is None:
        if ranking.resolution_status == "ambiguous_candidates" and ranking.ambiguity_reason:
            warnings.append(f"Tap resolution ambiguous: {ranking.ambiguity_reason}")
        else:
            warnings.append(
                "No primary selector candidate after ranking; step not planned for execution.",
            )
        return step.model_copy(
            update={
                "phase": RunStepPhase.SKIPPED_NO_SELECTOR,
                "ranking": ranking,
                "target_hints": hints,
                "planned_attempt": None,
                "warnings": warnings,
            },
        )
    return step.model_copy(
        update={
            "phase": RunStepPhase.PLANNED,
            "ranking": ranking,
            "target_hints": hints,
            "planned_attempt": planned,
            "warnings": warnings,
        },
    )
