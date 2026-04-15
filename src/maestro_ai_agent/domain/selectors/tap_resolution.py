"""Runtime tap resolution policy (deterministic ambiguity handling; no AI)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AmbiguityStrategy(StrEnum):
    """How to behave when multiple hierarchy-backed tap targets score similarly."""

    AUTO = "auto"
    SUGGEST = "suggest"
    FAIL = "fail"


class TapResolutionSettings(BaseModel):
    """Per-run settings threaded into selector ranking and planning."""

    ambiguity_strategy: AmbiguityStrategy = Field(
        default=AmbiguityStrategy.AUTO,
        description="auto: pick best ranked tap even when mildly ambiguous; suggest/fail: no plan.",
    )
    max_target_suggestions: int = Field(default=8, ge=1, le=50)
    show_target_regions: bool = Field(
        default=True,
        description="When false, omit coarse region hints from exported candidate summaries.",
    )
    prefer_target_kind: str = Field(
        default="auto",
        description="Structural bias: auto | tab | button | banner | menu_item.",
    )
