"""End-to-end deterministic selector planning (generate → rank)."""

from __future__ import annotations

from maestro_ai_agent.domain.enums import ActionType
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.generator import generate_proposals
from maestro_ai_agent.domain.selectors.intent_match import infer_target_hints
from maestro_ai_agent.domain.selectors.ranker import rank_selector_proposals
from maestro_ai_agent.domain.selectors.ranking_types import SelectorRankingResult
from maestro_ai_agent.domain.selectors.tap_resolution import TapResolutionSettings
from maestro_ai_agent.domain.selectors.target_hints import TargetHints


def plan_selector_ranking(
    hierarchy: HierarchySnapshot,
    intent: StepIntent,
    hints: TargetHints | None = None,
    *,
    tap_resolution: TapResolutionSettings | None = None,
) -> SelectorRankingResult:
    """
    Infer hints (unless provided), generate proposals, and rank them deterministically.

    This is the primary entrypoint for the observe→plan stages of the future orchestrator.
    """
    merged_hints = hints or infer_target_hints(intent)
    proposals = generate_proposals(hierarchy, intent, merged_hints)
    tr = tap_resolution or TapResolutionSettings()
    for_tap = intent.primary_action is ActionType.TAP
    return rank_selector_proposals(
        proposals,
        hierarchy,
        hints=merged_hints,
        tap_resolution=tr,
        for_tap=for_tap,
    )


def apply_ranking_to_intent(intent: StepIntent, ranking: SelectorRankingResult) -> StepIntent:
    """Attach ranked :class:`SelectorCandidate` rows to a :class:`StepIntent` (immutable copy)."""
    return intent.model_copy(
        update={"selector_candidates": [entry.candidate for entry in ranking.ordered]},
    )
