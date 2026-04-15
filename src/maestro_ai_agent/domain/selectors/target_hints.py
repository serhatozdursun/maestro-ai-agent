"""Hints used to steer deterministic selector generation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ControlKind(StrEnum):
    """Coarse control classification for matching."""

    UNKNOWN = "unknown"
    BUTTON = "button"
    EDITTEXT = "edittext"
    TEXTVIEW = "textview"


class TargetHints(BaseModel):
    """Optional steering hints layered on top of :class:`StepIntent` inference."""

    desired_texts: list[str] = Field(
        default_factory=list,
        description="Visible copy or literals the UI should expose (case-insensitive matching).",
    )
    semantic_keywords: list[str] = Field(
        default_factory=list,
        description="Normalized keywords (e.g. sign-in, add-to-cart) used for loose matching.",
    )
    preferred_control_kind: ControlKind = Field(
        default=ControlKind.UNKNOWN,
        description="Best-effort control class preference.",
    )
    container_hint: str | None = Field(
        default=None,
        description="Normalized contextual region slug from tap qualifiers (soft ranking bias).",
    )
    qualifier_phrase_raw: str | None = Field(
        default=None,
        description="Raw qualifier phrase after on/in/from (logging / reports).",
    )
    prefer_structural_kind: str = Field(
        default="auto",
        description="Coarse structural bias: auto | tab | button | banner | menu_item.",
    )
