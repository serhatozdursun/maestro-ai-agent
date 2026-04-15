"""Internal proposal model (pre-ranking). Not executed on device."""

from __future__ import annotations

from pydantic import BaseModel, Field

from maestro_ai_agent.domain.enums import SelectorType
from maestro_ai_agent.domain.selectors.evidence import SelectorEvidence


class ProposedSelector(BaseModel):
    """Deterministic selector hypothesis before scoring."""

    proposal_id: str = Field(min_length=1)
    selector_type: SelectorType
    expression: str | None = Field(
        default=None,
        description="Best-effort Maestro-oriented selector string; may be refined later.",
    )
    target_node_index: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence: list[SelectorEvidence] = Field(default_factory=list)
    relational_anchor_node_index: str | None = Field(
        default=None,
        description="Parent or anchor node used to reduce ambiguity, if any.",
    )
    is_point: bool = Field(default=False, description="True when derived from geometry only.")
