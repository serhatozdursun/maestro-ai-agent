"""
Runtime tap attempt ordering (separate from ranking order and YAML choice).

Ranking may prefer stable ids first for planning/YAML; Maestro ``tap_on`` often works
better with visible text at runtime, so execution tries text-shaped selectors before id.
"""

from __future__ import annotations

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.planning import quoted_literal_from_step_text
from maestro_ai_agent.domain.selectors.ranking_types import (
    RankedSelectorCandidate,
    SelectorRankingResult,
)
from maestro_ai_agent.orchestrator.models import PlannedActionAttempt


def _runtime_tap_tier(selector_type: SelectorType) -> int:
    """Lower tier = tried earlier at runtime (text-first)."""
    if selector_type in (SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
        return 0
    if selector_type is SelectorType.ID:
        return 1
    if selector_type is SelectorType.RELATIONAL:
        return 2
    if selector_type is SelectorType.POINT:
        return 3
    return 9


def runtime_tap_planned_attempts(
    intent: StepIntent,
    ranking: SelectorRankingResult,
    *,
    scenario_step_index: int,
) -> list[PlannedActionAttempt]:
    """
    Build ordered :class:`PlannedActionAttempt` rows for TAP runtime tries.

    Order: text (+ text_with_state) → id → relational → point; within a tier, higher
    score first. De-duplicates by ``candidate_id``. Does not change ranking.primary.
    """
    if intent.primary_action is not ActionType.TAP:
        return []

    ranked_rows: list[RankedSelectorCandidate] = []
    seen: set[str] = set()
    for row in ranking.ordered:
        expr = (row.candidate.expression or "").strip()
        if not expr:
            continue
        cid = row.candidate.candidate_id
        if cid in seen:
            continue
        seen.add(cid)
        ranked_rows.append(row)

    desired = (quoted_literal_from_step_text(intent.raw_step_text) or "").strip().lower()

    def _is_exact_desired_text(row: RankedSelectorCandidate) -> bool:
        if not desired:
            return False
        if row.candidate.selector_type not in (SelectorType.TEXT, SelectorType.TEXT_WITH_STATE):
            return False
        expr = (row.candidate.expression or "").strip()
        if not expr.lower().startswith("text:"):
            return False
        val = expr[5:].strip().lower()
        return bool(val) and val == desired

    ranked_rows.sort(
        key=lambda r: (
            0 if _is_exact_desired_text(r) else 1,
            _runtime_tap_tier(r.candidate.selector_type),
            -r.score,
            r.candidate.candidate_id,
        ),
    )

    out: list[PlannedActionAttempt] = []
    for pos, row in enumerate(ranked_rows):
        out.append(
            PlannedActionAttempt(
                intent_id=intent.intent_id,
                scenario_step_index=scenario_step_index,
                action=intent.primary_action,
                chosen_candidate_id=row.candidate.candidate_id,
                expression=row.candidate.expression,
                selector_type=row.candidate.selector_type,
                score=row.score,
                rank_position=pos,
                explanation_summary=row.explanation.summary,
            ),
        )
    return out
