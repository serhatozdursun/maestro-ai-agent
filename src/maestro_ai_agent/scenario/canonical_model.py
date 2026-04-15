"""Canonical scenario representation (independent of Maestro and orchestrator)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CanonicalStep(BaseModel):
    """
    One normalized step: what to do, at what target, optional value (e.g. input text).

    ``action`` is a stable slug (``tap``, ``search``, ``unknown``, …), not a Maestro command.
    """

    action: str = Field(min_length=1, description="Normalized verb / intent slug.")
    target: str | None = Field(default=None, description="Primary UI or entity reference.")
    value: str | None = Field(default=None, description="Secondary payload (e.g. typed text).")
    index: int = Field(ge=0, description="Zero-based order in the scenario.")
    source_text: str | None = Field(
        default=None,
        description="Original line or clause for traceability.",
    )
    target_qualifier_phrase_raw: str | None = Field(
        default=None,
        description="Raw qualifier text after on/in/from (optional tap context).",
    )
    target_container_hint: str | None = Field(
        default=None,
        description="Normalized contextual hint slug (e.g. ``tab_bar``) when synonyms matched.",
    )
    tap_qualifier_preposition: str | None = Field(
        default=None,
        description="``on``, ``in``, or ``from`` as parsed from the tap line.",
    )


class CanonicalScenario(BaseModel):
    """Full scenario after classification + parsing (+ optional AI touch-up)."""

    steps: list[CanonicalStep] = Field(default_factory=list)
    title: str | None = Field(default=None, description="Optional scenario title (e.g. Gherkin).")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal parse notes.")
