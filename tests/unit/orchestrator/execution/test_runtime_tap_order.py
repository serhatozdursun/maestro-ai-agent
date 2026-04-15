"""Runtime tap attempt order (text-first) vs ranking order."""

from uuid import uuid4

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selector import SelectorCandidate
from maestro_ai_agent.domain.selectors.evidence import EvidenceKind, SelectorEvidence
from maestro_ai_agent.domain.selectors.explanation import SelectorExplanation, SelectorReasonCode
from maestro_ai_agent.domain.selectors.ranking_types import (
    RankedSelectorCandidate,
    SelectorRankingResult,
)
from maestro_ai_agent.orchestrator.execution.runtime_tap_order import runtime_tap_planned_attempts


def _ranked(
    *,
    cid: str,
    expr: str,
    stype: SelectorType,
    score: float,
) -> RankedSelectorCandidate:
    return RankedSelectorCandidate(
        candidate=SelectorCandidate(
            candidate_id=cid,
            selector_type=stype,
            expression=expr,
            rationale="test",
            rank=0,
            confidence=ConfidenceScore(value=0.8),
        ),
        score=score,
        evidence=[SelectorEvidence(kind=EvidenceKind.VISIBLE_TEXT, weight=0.5, detail="x")],
        explanation=SelectorExplanation(
            codes=[SelectorReasonCode.FALLBACK_CANDIDATE_ONLY],
            summary="test",
        ),
    )


def test_runtime_tap_order_prefers_text_before_id_despite_higher_id_score() -> None:
    """Ranking order can be id-first; runtime tries text-shaped selectors first."""
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'X'",
        validation_goals=[],
    )
    id_row = _ranked(cid="i1", expr="id:bag", stype=SelectorType.ID, score=0.95)
    text_row = _ranked(cid="t1", expr="text:Cart", stype=SelectorType.TEXT, score=0.7)
    ranking = SelectorRankingResult(ordered=[id_row, text_row], primary=id_row)
    attempts = runtime_tap_planned_attempts(intent, ranking, scenario_step_index=0)
    assert [a.selector_type for a in attempts] == [SelectorType.TEXT, SelectorType.ID]
    assert attempts[0].expression == "text:Cart"
    assert attempts[1].expression == "id:bag"


def test_runtime_tap_order_id_before_relational() -> None:
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'X'",
        validation_goals=[],
    )
    rel = _ranked(cid="r1", expr="childOf", stype=SelectorType.RELATIONAL, score=0.99)
    idc = _ranked(cid="i1", expr="id:a", stype=SelectorType.ID, score=0.5)
    ranking = SelectorRankingResult(ordered=[rel, idc], primary=rel)
    attempts = runtime_tap_planned_attempts(intent, ranking, scenario_step_index=0)
    assert [a.selector_type for a in attempts] == [SelectorType.ID, SelectorType.RELATIONAL]


def test_runtime_tap_order_prefers_exact_desired_text_literal_first() -> None:
    """For Tap 'Add To Bag', exact text candidate should be tried before generic text/id."""
    intent = StepIntent(
        intent_id=uuid4(),
        scenario_step_index=0,
        primary_action=ActionType.TAP,
        goal_summary="tap",
        raw_step_text="Tap 'Add To Bag'",
        validation_goals=[],
    )
    id_row = _ranked(cid="i1", expr="id:CartButton", stype=SelectorType.ID, score=12.16)
    txt_cart = _ranked(cid="t1", expr="text:Cart", stype=SelectorType.TEXT, score=8.06)
    txt_exact = _ranked(cid="t2", expr="text:Add To Bag", stype=SelectorType.TEXT, score=6.40)
    ranking = SelectorRankingResult(ordered=[id_row, txt_cart, txt_exact], primary=id_row)
    attempts = runtime_tap_planned_attempts(intent, ranking, scenario_step_index=0)
    assert attempts[0].expression == "text:Add To Bag"
