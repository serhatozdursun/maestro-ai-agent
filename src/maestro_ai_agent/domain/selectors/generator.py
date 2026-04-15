"""Deterministic selector candidate generation from hierarchy + intent."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from maestro_ai_agent.domain.enums import ActionType, SelectorType
from maestro_ai_agent.domain.hierarchy import (
    HierarchyNode,
    HierarchySnapshot,
    effective_visible_text,
)
from maestro_ai_agent.domain.intent import StepIntent
from maestro_ai_agent.domain.selectors.evidence import EvidenceKind, SelectorEvidence
from maestro_ai_agent.domain.selectors.intent_match import infer_target_hints
from maestro_ai_agent.domain.selectors.proposal import ProposedSelector
from maestro_ai_agent.domain.selectors.target_hints import ControlKind, TargetHints

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _input_like(class_name: str | None) -> bool:
    if not class_name:
        return False
    lowered = class_name.lower()
    return any(
        token in lowered
        for token in (
            "edittext",
            "textfield",
            "uitextfield",
            "textinput",
            "autocompletetextview",
            "securefield",
        )
    )


def _button_like(class_name: str | None) -> bool:
    if not class_name:
        return False
    lowered = class_name.lower()
    return any(token in lowered for token in ("button", "imagebutton", "uibutton"))


def bounds_center(bounds: str | None) -> tuple[int, int] | None:
    """Return the center point of Maestro ``bounds=[x,y][x,y]`` strings, if parseable."""
    if not bounds:
        return None
    match = _BOUNDS.search(bounds)
    if not match:
        return None
    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _indexes(
    nodes: list[HierarchyNode],
) -> tuple[
    dict[str, HierarchyNode],
    dict[str, list[HierarchyNode]],
    Counter[str],
    Counter[str],
]:
    by_index = {node.node_index: node for node in nodes}
    children: dict[str, list[HierarchyNode]] = defaultdict(list)
    for node in nodes:
        parent_key = node.parent_index or ""
        children[parent_key].append(node)
    rid_counts = Counter(node.resource_id for node in nodes if node.resource_id)
    text_counts = Counter(
        effective_visible_text(node).lower() for node in nodes if effective_visible_text(node)
    )
    return by_index, children, rid_counts, text_counts


def _maestro_id_expression(resource_id: str) -> str:
    return f"id:{resource_id}"


def _maestro_text_expression(text: str) -> str:
    cleaned = " ".join(text.split())
    return f"text:{cleaned}"


def _maestro_point_expression(cx: int, cy: int) -> str:
    return f"point:{cx},{cy}"


def _dedupe_key(proposal: ProposedSelector) -> tuple[str, str, str | None]:
    return (proposal.selector_type.value, proposal.target_node_index, proposal.expression)


def generate_proposals(
    hierarchy: HierarchySnapshot,
    intent: StepIntent,
    hints: TargetHints | None = None,
) -> list[ProposedSelector]:
    """
    Produce plausible :class:`ProposedSelector` rows for the given hierarchy and intent.

    The generator is conservative: it prefers id/text evidence, adds modest relational
    disambiguation when duplicate visible text exists, and only emits ``point`` proposals
    when geometry is available (still heavily down-ranked later).
    """
    hints = hints or infer_target_hints(intent)
    nodes = hierarchy.nodes
    by_index, children, _, text_counts = _indexes(nodes)
    proposals: list[ProposedSelector] = []
    seen: set[tuple[str, str, str | None]] = set()

    def append(proposal: ProposedSelector) -> None:
        key = _dedupe_key(proposal)
        if key in seen:
            return
        seen.add(key)
        pid = f"prop-{len(proposals):04d}"
        proposals.append(proposal.model_copy(update={"proposal_id": pid}))

    hint_tokens = [h.lower() for h in hints.desired_texts + hints.semantic_keywords if h.strip()]
    expanded_tokens: list[str] = []
    for token in hint_tokens:
        expanded_tokens.append(token)
        for piece in token.replace("-", " ").replace("_", " ").split():
            if piece:
                expanded_tokens.append(piece)

    # Resource-id matches (substring) against hints.
    for node in nodes:
        if not node.resource_id:
            continue
        rid_lower = node.resource_id.lower()
        if not any(fragment and fragment in rid_lower for fragment in expanded_tokens):
            continue
        evidence = [
            SelectorEvidence(
                kind=EvidenceKind.RESOURCE_ID,
                weight=0.9,
                detail=f"resource-id contains planner hint ({node.resource_id})",
            )
        ]
        append(
            ProposedSelector(
                proposal_id="pending",
                selector_type=SelectorType.ID,
                expression=_maestro_id_expression(node.resource_id),
                target_node_index=node.node_index,
                rationale="Matched planner hint against resource-id attribute.",
                evidence=evidence,
            )
        )

    # Visible text / semantic matches.
    for node in nodes:
        visible = effective_visible_text(node)
        if not visible:
            continue
        lowered = visible.lower()
        matched_desired = [
            h for h in hints.desired_texts if h.lower() in lowered or lowered in h.lower()
        ]
        matched_semantic = [k for k in hints.semantic_keywords if k.lower() in lowered]

        if not matched_desired and not matched_semantic:
            continue

        evidence: list[SelectorEvidence] = []
        if matched_desired:
            evidence.append(
                SelectorEvidence(
                    kind=EvidenceKind.VISIBLE_TEXT,
                    weight=0.85,
                    detail=f"Visible text overlaps desired literals: {', '.join(matched_desired)}",
                )
            )
        if matched_semantic:
            evidence.append(
                SelectorEvidence(
                    kind=EvidenceKind.SEMANTIC_KEYWORD,
                    weight=0.65,
                    detail=f"Visible text matches semantic keywords: {', '.join(matched_semantic)}",
                )
            )
        if node.class_name:
            evidence.append(
                SelectorEvidence(
                    kind=EvidenceKind.CLASS_HINT,
                    weight=0.35,
                    detail=f"class={node.class_name}",
                )
            )

        dup_count = text_counts.get(lowered, 0)
        selector_type = SelectorType.TEXT
        relational_anchor: str | None = None
        rationale = "Matched visible text against planner hints."
        if dup_count > 1 and node.parent_index:
            parent = by_index.get(node.parent_index)
            if parent and parent.resource_id:
                selector_type = SelectorType.RELATIONAL
                relational_anchor = parent.node_index
                rationale += (
                    " Duplicate visible text disambiguated using parent resource-id context."
                )
                evidence.append(
                    SelectorEvidence(
                        kind=EvidenceKind.PARENT_CONTEXT,
                        weight=0.75,
                        detail=f"Parent container resource-id={parent.resource_id}",
                    )
                )

        append(
            ProposedSelector(
                proposal_id="pending",
                selector_type=selector_type,
                expression=_maestro_text_expression(visible),
                target_node_index=node.node_index,
                rationale=rationale,
                evidence=evidence,
                relational_anchor_node_index=relational_anchor,
            )
        )

    # Tab / icon rows: tap label on parent with resource-id only on child (e.g. Cart + bag).
    if intent.primary_action is ActionType.TAP:
        for parent in nodes:
            pvis = effective_visible_text(parent)
            if not pvis:
                continue
            lowered = pvis.lower()
            matched_label = [
                h
                for h in hints.desired_texts
                if h.strip() and (h.lower() in lowered or lowered in h.lower())
            ]
            if not matched_label:
                continue
            for child in children.get(parent.node_index, []):
                if not child.resource_id:
                    continue
                if effective_visible_text(child):
                    continue
                evidence = [
                    SelectorEvidence(
                        kind=EvidenceKind.PARENT_CONTEXT,
                        weight=0.72,
                        detail=(
                            f"Tap target resource-id={child.resource_id!r} under row matching "
                            f"{', '.join(matched_label)}"
                        ),
                    )
                ]
                append(
                    ProposedSelector(
                        proposal_id="pending",
                        selector_type=SelectorType.ID,
                        expression=_maestro_id_expression(child.resource_id),
                        target_node_index=child.node_index,
                        rationale=(
                            "Resource id on child under a parent row that matches the tap label."
                        ),
                        evidence=evidence,
                        relational_anchor_node_index=parent.node_index,
                    )
                )

    # Input proximity: sibling labels under the same parent.
    wants_input = (
        intent.primary_action is ActionType.INPUT_TEXT
        or hints.preferred_control_kind is ControlKind.EDITTEXT
    )
    if wants_input:
        for _parent_key, siblings in children.items():
            edits = [node for node in siblings if _input_like(node.class_name)]
            if not edits:
                continue
            for edit in edits:
                for sibling in siblings:
                    if sibling.node_index == edit.node_index:
                        continue
                    sib_text = effective_visible_text(sibling)
                    if not sib_text:
                        continue
                    label_match = any(
                        desired.lower() in sib_text.lower() for desired in hints.desired_texts
                    )
                    if not label_match:
                        continue
                    evidence = [
                        SelectorEvidence(
                            kind=EvidenceKind.PROXIMITY_LABEL,
                            weight=0.8,
                            detail=f"Sibling label '{sib_text}' aligns with desired field text.",
                        )
                    ]
                    if edit.resource_id:
                        evidence.append(
                            SelectorEvidence(
                                kind=EvidenceKind.RESOURCE_ID,
                                weight=0.7,
                                detail=f"Input control resource-id={edit.resource_id}",
                            )
                        )
                        append(
                            ProposedSelector(
                                proposal_id="pending",
                                selector_type=SelectorType.ID,
                                expression=_maestro_id_expression(edit.resource_id),
                                target_node_index=edit.node_index,
                                rationale=(
                                    "Input control near a sibling label matching desired text."
                                ),
                                evidence=evidence,
                                relational_anchor_node_index=sibling.node_index,
                            )
                        )
                    else:
                        evidence.append(
                            SelectorEvidence(
                                kind=EvidenceKind.VISIBLE_TEXT,
                                weight=0.55,
                                detail=(
                                    "Input control lacks stable id; fall back to text targeting."
                                ),
                            )
                        )
                        append(
                            ProposedSelector(
                                proposal_id="pending",
                                selector_type=SelectorType.TEXT,
                                expression=_maestro_text_expression(
                                    effective_visible_text(edit) or sib_text
                                ),
                                target_node_index=edit.node_index,
                                rationale="Input-like control near descriptive sibling label.",
                                evidence=evidence,
                                relational_anchor_node_index=sibling.node_index,
                            )
                        )

    # Tap-oriented fallbacks when hints suggest buttons but no text match yet.
    tap_button = (
        intent.primary_action is ActionType.TAP
        and hints.preferred_control_kind is ControlKind.BUTTON
    )
    if tap_button:
        for node in nodes:
            if not _button_like(node.class_name):
                continue
            visible = effective_visible_text(node)
            if not visible:
                continue
            if any(proposal.target_node_index == node.node_index for proposal in proposals):
                continue
            if not any(keyword in visible.lower() for keyword in hints.semantic_keywords):
                continue
            append(
                ProposedSelector(
                    proposal_id="pending",
                    selector_type=SelectorType.TEXT,
                    expression=_maestro_text_expression(visible),
                    target_node_index=node.node_index,
                    rationale="Button-like control matched semantic keyword heuristics.",
                    evidence=[
                        SelectorEvidence(
                            kind=EvidenceKind.SEMANTIC_KEYWORD,
                            weight=0.55,
                            detail=f"Button text '{visible}' matches semantic hints.",
                        )
                    ],
                )
            )

    # Point fallback for the strongest text match with bounds (still heavily penalized later).
    text_nodes = [
        node for node in nodes if effective_visible_text(node) and bounds_center(node.bounds)
    ]
    if text_nodes:
        best = max(
            text_nodes,
            key=lambda n: sum(
                1
                for fragment in expanded_tokens
                if fragment and fragment in effective_visible_text(n).lower()
            ),
        )
        center = bounds_center(best.bounds)
        if (
            center
            and expanded_tokens
            and any(
                fragment in effective_visible_text(best).lower()
                for fragment in expanded_tokens
                if fragment
            )
        ):
            cx, cy = center
            append(
                ProposedSelector(
                    proposal_id="pending",
                    selector_type=SelectorType.POINT,
                    expression=_maestro_point_expression(cx, cy),
                    target_node_index=best.node_index,
                    rationale=(
                        "Geometry-based fallback when textual selectors exist but may be brittle."
                    ),
                    evidence=[
                        SelectorEvidence(
                            kind=EvidenceKind.POINT_GEOMETRY,
                            weight=0.2,
                            detail=f"Derived center ({cx}, {cy}) from bounds.",
                        )
                    ],
                    is_point=True,
                )
            )

    return proposals
