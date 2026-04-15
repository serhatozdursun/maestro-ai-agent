"""Scenario capture and deterministic parsing outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from maestro_ai_agent.domain.enums import Platform


class ScenarioInput(BaseModel):
    """User-provided scenario plus run metadata (no device IO)."""

    scenario_text: str = Field(min_length=1, description="Natural-language scenario body.")
    app_id: str = Field(min_length=1, description="Application id / bundle id for Maestro launch.")
    platform: Platform
    title: str | None = Field(default=None, description="Optional short label for reports.")

    @field_validator("scenario_text")
    @classmethod
    def scenario_not_blank(cls, v: str) -> str:
        if not v.strip():
            msg = "must not be empty or whitespace-only"
            raise ValueError(msg)
        return v

    @field_validator("app_id")
    @classmethod
    def strip_app_id(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            msg = "must not be empty or whitespace-only"
            raise ValueError(msg)
        return stripped


class ScenarioStep(BaseModel):
    """One atomic line derived from the scenario (pre-intent)."""

    index: int = Field(ge=0, description="Zero-based order in the parsed scenario.")
    text: str = Field(min_length=1, description="Normalized step text.")
    source_line: int | None = Field(
        default=None,
        description="1-based line number in the original scenario text, if known.",
    )
    canonical_action: str | None = Field(
        default=None,
        description=(
            "When set (e.g. canonical normalization path), deterministic slug from "
            ":class:`~maestro_ai_agent.scenario.canonical_model.CanonicalStep.action` "
            "used as the authoritative planner action instead of re-inferring from ``text``."
        ),
    )


class ParsedScenario(BaseModel):
    """Structured scenario after deterministic first-pass parsing."""

    input: ScenarioInput
    steps: list[ScenarioStep] = Field(default_factory=list)
    parser_name: str = Field(
        default="deterministic_line_v1",
        description="Identifier of the parser implementation for traceability.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues detected during parsing (e.g. skipped blank lines).",
    )
