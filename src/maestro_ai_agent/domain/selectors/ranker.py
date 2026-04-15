"""Deterministic scoring and ranking for selector proposals."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from maestro_ai_agent.domain.confidence import ConfidenceScore
from maestro_ai_agent.domain.enums import SelectorType
from maestro_ai_agent.domain.hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    effective_visible_text,
)
from maestro_ai_agent.domain.selector import SelectorCandidate
from maestro_ai_agent.domain.selectors.candidate_geometry import (
    NodeBounds,
    hierarchy_screen_bbox,
    infer_node_structural_hints,
    parse_node_bounds,
)
from maestro_ai_agent.domain.selectors.evidence import EvidenceKind
from maestro_ai_agent.domain.selectors.explanation import SelectorExplanation, SelectorReasonCode
from maestro_ai_agent.domain.selectors.proposal import ProposedSelector
from maestro_ai_agent.domain.selectors.ranking_types import (
    RankedSelectorCandidate,
    SelectorFallbackGroup,
    SelectorRankingResult,
    SelectorResolutionStatus,
)
from maestro_ai_agent.domain.selectors.tap_resolution import (
    AmbiguityStrategy,
    TapResolutionSettings,
)
from maestro_ai_agent.domain.selectors.target_hints import TargetHints

_TYPE_PRIORITY = {
    SelectorType.ID: 0,
    SelectorType.TEXT: 1,
    SelectorType.TEXT_WITH_STATE: 2,
    SelectorType.RELATIONAL: 3,
    SelectorType.POINT: 99,
}


def _find_node(hierarchy: HierarchySnapshot, node_index: str) -> HierarchyNode | None:
    return next((n for n in hierarchy.nodes if n.node_index == node_index), None)


@dataclass
class _ScoredRow:
    score: float
    priority: int
    proposal: ProposedSelector
    explanation: SelectorExplanation
    struct: object | None
    ctx_delta: float
    ctx_notes: list[str]
    preferred: bool
    sk_label: str
    node: object | None


_SHORT_NAV_TOKENS = frozenset(
    {
        "shop",
        "home",
        "search",
        "cart",
        "menu",
        "filter",
        "close",
        "account",
        "profile",
        "orders",
        "wishlist",
        "bag",
        "browse",
        "continue",
        "next",
    },
)


def _structural_kind_label(struct: object | None) -> str:
    if struct is None:
        return "neutral"
    # NodeStructuralHints duck-typed; bottom-nav children rank as tab-like for ambiguity checks.
    if getattr(struct, "is_tab_like", False) or getattr(struct, "is_nav_container_child", False):
        return "tab_like"
    if getattr(struct, "is_banner_like", False):
        return "banner_like"
    if getattr(struct, "is_button_like", False):
        return "button_like"
    if getattr(struct, "is_header_like", False):
        return "header_like"
    if getattr(struct, "is_list_row_like", False):
        return "menu_item_like"
    return "neutral"


def _bounds_dict(nb: NodeBounds | None) -> dict[str, float] | None:
    if nb is None:
        return None
    return {"left": nb.left, "top": nb.top, "right": nb.right, "bottom": nb.bottom}


def _contextual_adjustment(
    *,
    proposal: ProposedSelector,
    node,
    struct: object | None,
    hints: TargetHints,
    text_counts: Counter[str],
    for_tap: bool,
) -> tuple[float, list[str], bool, str]:
    """Soft bias from optional tap qualifiers + duplicate short-label heuristics."""
    sk = _structural_kind_label(struct)
    if not for_tap:
        return 0.0, [], False, sk

    notes: list[str] = []
    delta = 0.0
    preferred = False
    ch = hints.container_hint
    pkind = (hints.prefer_structural_kind or "auto").strip().lower()

    def _s(name: str) -> bool:
        return bool(struct and getattr(struct, name, False))

    if pkind == "tab":
        if _s("is_tab_like") or _s("is_nav_container_child"):
            delta += 3.0
            notes.append("prefer_target_kind=tab boosts tab-like / bottom-nav context.")
        if _s("is_banner_like"):
            delta -= 2.5
    elif pkind == "button":
        if _s("is_button_like"):
            delta += 3.0
        if _s("is_banner_like"):
            delta -= 1.5
    elif pkind == "banner":
        if _s("is_banner_like"):
            delta += 3.0
    elif pkind == "menu_item":
        if _s("is_list_row_like"):
            delta += 3.0

    if ch == "tab_bar":
        if _s("is_tab_like") or _s("is_nav_container_child"):
            delta += 4.5
            notes.append("container_hint=tab_bar boosts tab / bottom-nav candidates.")
            preferred = _s("is_nav_container_child") or _s("is_tab_like")
        if _s("is_banner_like"):
            delta -= 5.0
            notes.append("container_hint=tab_bar penalizes banner-like surfaces.")
        rh = getattr(struct, "region_hint", None) if struct else None
        if rh and "bottom" in str(rh):
            delta += 1.5
    elif ch == "header":
        if _s("is_header_like"):
            delta += 4.0
            preferred = _s("is_header_like")
        rh = getattr(struct, "region_hint", None) if struct else None
        if rh and str(rh).startswith("top"):
            delta += 1.5
        if _s("is_tab_like") or _s("is_nav_container_child"):
            delta -= 3.0
            notes.append("container_hint=header penalizes bottom navigation/tab strip.")
    elif ch == "modal":
        if _s("is_modal_child"):
            delta += 5.0
            preferred = _s("is_modal_child")
        elif struct is not None:
            delta -= 1.2
            notes.append("container_hint=modal mildly penalizes non-modal surfaces.")
    elif ch == "footer":
        rh = getattr(struct, "region_hint", None) if struct else None
        if rh and "bottom" in str(rh):
            delta += 2.5
    elif ch == "drawer":
        if _s("is_nav_container_child"):
            delta += 1.8
    elif ch == "search_field":
        cls = (node.class_name or "").lower() if node else ""
        if "edittext" in cls or "uitextfield" in cls or "search" in cls:
            delta += 3.5
            preferred = True

    primary_desired = hints.desired_texts[0].lower().strip() if hints.desired_texts else ""
    visible = (effective_visible_text(node).lower() if node else "") or ""
    resource_id = (node.resource_id.lower() if node and node.resource_id else "") or ""
    desired_tokens = [t for t in primary_desired.replace("-", " ").split() if t]
    if primary_desired and visible == primary_desired:
        dup = text_counts.get(primary_desired, 0)
        # Strongly prefer exact literal matches for user-authored tap text.
        delta += 4.0
        notes.append("Exact desired tap literal matches visible text.")
        if dup > 1 and primary_desired in _SHORT_NAV_TOKENS and struct is not None:
            if _s("is_banner_like"):
                delta -= 5.5
                notes.append("Short nav label duplicated; de-prioritize banner-like match.")
            if _s("is_tab_like") or _s("is_nav_container_child") or _s("is_button_like"):
                delta += 3.2
                notes.append("Short nav label duplicated; boost control-like match.")
    elif primary_desired and len(desired_tokens) >= 2:
        # When step text is specific (multi-token), penalize candidates that don't contain
        # enough literal evidence (e.g. "Tap Add To Bag" picking CartButton).
        token_hits = sum(
            1
            for tok in desired_tokens
            if tok in visible or tok in resource_id or tok in proposal.expression.lower()
        )
        if token_hits == 0:
            delta -= 4.5
            notes.append("Multi-token desired literal absent in candidate text/id.")
        elif token_hits == 1:
            delta -= 2.0
            notes.append("Only weak partial match for multi-token desired literal.")

    return delta, notes, preferred, sk


def _visible_text_counts(nodes: HierarchySnapshot) -> Counter[str]:
    return Counter(
        effective_visible_text(node).lower() for node in nodes.nodes if effective_visible_text(node)
    )


def _resource_id_counts(nodes: HierarchySnapshot) -> Counter[str]:
    return Counter(node.resource_id for node in nodes.nodes if node.resource_id)


def _score_and_explain(
    proposal: ProposedSelector,
    hierarchy: HierarchySnapshot,
) -> tuple[float, SelectorExplanation]:
    codes: list[SelectorReasonCode] = []
    notes: list[str] = []

    base = sum(item.weight for item in proposal.evidence) * 2.4
    score = base

    rid_counts = _resource_id_counts(hierarchy)
    text_counts = _visible_text_counts(hierarchy)
    node = next((n for n in hierarchy.nodes if n.node_index == proposal.target_node_index), None)

    if proposal.selector_type is SelectorType.POINT or proposal.is_point:
        score -= 18.0
        codes.append(SelectorReasonCode.POINT_LAST_RESORT)
        notes.append("Point-based targeting is a last resort and is heavily penalized.")

    if proposal.selector_type is SelectorType.ID and node and node.resource_id:
        if rid_counts.get(node.resource_id, 0) == 1:
            score += 6.0
            codes.append(SelectorReasonCode.UNIQUE_ID_MATCH)
            notes.append("Resource id appears unique on this screen.")
            # Policy: stable resource identifiers beat plain text when both exist.
            score += 4.0
        else:
            score += 2.0
            notes.append("Resource id is shared by multiple nodes; lower confidence.")

    if proposal.selector_type in {SelectorType.TEXT, SelectorType.RELATIONAL} and node:
        visible = effective_visible_text(node).lower()
        if visible:
            dup = text_counts.get(visible, 0)
            if dup == 1:
                score += 5.0
                codes.append(SelectorReasonCode.EXACT_VISIBLE_TEXT_MATCH)
                notes.append("Visible text is unique among siblings on this snapshot.")
            elif dup > 1:
                score -= 3.5
                notes.append("Visible text is duplicated; ambiguity increases.")
                if proposal.relational_anchor_node_index:
                    score += 3.0
                    codes.append(SelectorReasonCode.AMBIGUITY_REDUCED_BY_PARENT)
                    notes.append("Parent/anchor context reduces duplicate text ambiguity.")

    if any(ev.kind is EvidenceKind.SEMANTIC_KEYWORD for ev in proposal.evidence):
        score += 1.5
        codes.append(SelectorReasonCode.KEYWORD_SEMANTIC_MATCH)

    if any(ev.kind is EvidenceKind.PROXIMITY_LABEL for ev in proposal.evidence):
        score += 2.0
        codes.append(SelectorReasonCode.INPUT_NEAR_EXPECTED_LABEL)

    if any(ev.kind is EvidenceKind.CLASS_HINT for ev in proposal.evidence):
        score += 0.5

    if score <= 0.5 and SelectorReasonCode.POINT_LAST_RESORT not in codes:
        codes.append(SelectorReasonCode.FALLBACK_CANDIDATE_ONLY)
        notes.append("Low aggregate score; treat as fallback only.")

    # Deduplicate codes while preserving order
    ordered_codes: list[SelectorReasonCode] = []
    for code in codes:
        if code not in ordered_codes:
            ordered_codes.append(code)

    summary = "; ".join(notes) if notes else proposal.rationale
    explanation = SelectorExplanation(codes=ordered_codes, summary=summary)
    return score, explanation


def _confidence_from_score(score: float) -> ConfidenceScore:
    normalized = (score + 12.0) / 28.0
    return ConfidenceScore(value=max(0.0, min(1.0, normalized)))


def _tap_ambiguity_decision(
    ordered: list[RankedSelectorCandidate],
    *,
    hints: TargetHints,
    text_counts: Counter[str],
) -> tuple[bool, str]:
    if len(ordered) < 2:
        return False, ""
    top, second = ordered[0], ordered[1]
    gap = top.score - second.score
    sk0 = top.structural_kind or "neutral"
    sk1 = second.structural_kind or "neutral"
    tab_banner = ("tab" in sk0 and "banner" in sk1) or ("banner" in sk0 and "tab" in sk1)
    desired = hints.desired_texts[0].lower().strip() if hints.desired_texts else ""
    dup = bool(desired) and text_counts.get(desired, 0) > 1
    short_nav = desired in _SHORT_NAV_TOKENS
    ambiguous = gap < 4.0 and (tab_banner or (dup and short_nav and sk0 != sk1))
    reason = (
        f"top_two_gap={gap:.2f}; first={sk0}; second={sk1}; "
        f"dup_short_nav={dup and short_nav}; tab_vs_banner={tab_banner}"
    )
    return ambiguous, reason


def _finalize_primary_for_tap(
    ordered: list[RankedSelectorCandidate],
    *,
    hints: TargetHints,
    text_counts: Counter[str],
    tap_resolution: TapResolutionSettings,
) -> tuple[RankedSelectorCandidate | None, SelectorResolutionStatus, str | None]:
    if not ordered:
        return None, "not_found", "No selector proposals matched the hierarchy-backed plan."
    ambiguous, reason = _tap_ambiguity_decision(ordered, hints=hints, text_counts=text_counts)
    if not ambiguous:
        return ordered[0], "resolved", None
    if tap_resolution.ambiguity_strategy is AmbiguityStrategy.AUTO:
        return ordered[0], "ambiguous_candidates", reason + "; strategy=auto (best retained)."
    return None, "ambiguous_candidates", reason + f"; strategy={tap_resolution.ambiguity_strategy}."


def rank_selector_proposals(
    proposals: list[ProposedSelector],
    hierarchy: HierarchySnapshot,
    *,
    hints: TargetHints | None = None,
    tap_resolution: TapResolutionSettings | None = None,
    for_tap: bool = False,
) -> SelectorRankingResult:
    """
    Score proposals deterministically and return ordered ranking results.

    When ``for_tap`` is true, optional :class:`TargetHints` contextual fields influence scores
    softly, and tap ambiguity policy can clear ``primary`` for suggest/fail strategies.
    """
    merged_hints = hints or TargetHints()
    tr = tap_resolution or TapResolutionSettings()
    text_counts = _visible_text_counts(hierarchy)
    screen = hierarchy_screen_bbox(hierarchy)
    struct_by_index: dict[str, object] = {}
    for n in hierarchy.nodes:
        struct_by_index[n.node_index] = infer_node_structural_hints(
            n,
            hierarchy=hierarchy,
            screen=screen,
        )

    scored: list[_ScoredRow] = []
    for proposal in proposals:
        score, explanation = _score_and_explain(proposal, hierarchy)
        node = _find_node(hierarchy, proposal.target_node_index)
        struct = struct_by_index.get(proposal.target_node_index) if node else None
        ctx_delta, ctx_notes, preferred, sk_label = _contextual_adjustment(
            proposal=proposal,
            node=node,
            struct=struct,
            hints=merged_hints,
            text_counts=text_counts,
            for_tap=for_tap,
        )
        score += ctx_delta
        if ctx_notes:
            extra = "; ".join(ctx_notes)
            explanation = explanation.model_copy(
                update={"summary": f"{explanation.summary} {extra}".strip()},
            )
        priority = _TYPE_PRIORITY.get(proposal.selector_type, 50)
        scored.append(
            _ScoredRow(
                score=score,
                priority=priority,
                proposal=proposal,
                explanation=explanation,
                struct=struct,
                ctx_delta=ctx_delta,
                ctx_notes=ctx_notes,
                preferred=preferred,
                sk_label=sk_label,
                node=node,
            ),
        )

    scored.sort(key=lambda row: (-row.score, row.priority, row.proposal.target_node_index))

    ordered: list[RankedSelectorCandidate] = []
    for rank, row in enumerate(scored):
        confidence = _confidence_from_score(row.score)
        candidate = SelectorCandidate(
            candidate_id=row.proposal.proposal_id,
            selector_type=row.proposal.selector_type,
            expression=row.proposal.expression,
            rationale=row.proposal.rationale,
            rank=rank,
            confidence=confidence,
        )
        nb = parse_node_bounds(row.node) if row.node else None
        region = getattr(row.struct, "region_hint", None) if row.struct is not None else None
        ranking_notes = list(row.ctx_notes)
        if row.ctx_delta:
            ranking_notes.append(f"contextual_delta={row.ctx_delta:+.2f}")
        ordered.append(
            RankedSelectorCandidate(
                candidate=candidate,
                score=row.score,
                evidence=list(row.proposal.evidence),
                explanation=row.explanation,
                region_hint=region,
                bounds=_bounds_dict(nb),
                structural_kind=row.sk_label,
                preferred_for_qualifier=row.preferred,
                ranking_notes=ranking_notes,
            ),
        )

    if not ordered:
        return SelectorRankingResult(
            ordered=[],
            primary=None,
            fallback_groups=[],
            resolution_status="not_found",
            ambiguity_reason="No selector proposals matched the hierarchy-backed plan.",
        )

    primary: RankedSelectorCandidate | None
    resolution_status: SelectorResolutionStatus
    ambiguity_reason: str | None

    if for_tap:
        primary, resolution_status, ambiguity_reason = _finalize_primary_for_tap(
            ordered,
            hints=merged_hints,
            text_counts=text_counts,
            tap_resolution=tr,
        )
    else:
        primary = ordered[0]
        resolution_status = "resolved"
        ambiguity_reason = None

    fallback_members = (
        [c for c in ordered if c.candidate.candidate_id != primary.candidate.candidate_id]
        if primary is not None
        else list(ordered)
    )
    fallback_groups: list[SelectorFallbackGroup] = []
    if len(ordered) > 1:
        fallback_groups.append(
            SelectorFallbackGroup(
                label="ordered_alternates",
                members=fallback_members,
            ),
        )

    return SelectorRankingResult(
        ordered=ordered,
        primary=primary,
        fallback_groups=fallback_groups,
        resolution_status=resolution_status,
        ambiguity_reason=ambiguity_reason,
    )
