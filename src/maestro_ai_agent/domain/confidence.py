"""Numeric and discrete confidence representation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from maestro_ai_agent.domain.enums import ConfidenceLevel


class ConfidenceScore(BaseModel):
    """Bounded numeric confidence with optional discrete level and notes."""

    value: float = Field(ge=0.0, le=1.0, description="0.0 (no confidence) to 1.0 (strong).")
    level: ConfidenceLevel | None = Field(
        default=None,
        description="Optional explicit level; if omitted it is derived from value.",
    )
    notes: str | None = Field(default=None, description="Human-readable rationale.")

    @model_validator(mode="before")
    @classmethod
    def derive_level(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("level") is not None:
            return data
        value = data.get("value")
        if not isinstance(value, (int, float)):
            return data
        if value >= 0.67:
            data["level"] = ConfidenceLevel.HIGH
        elif value >= 0.34:
            data["level"] = ConfidenceLevel.MEDIUM
        else:
            data["level"] = ConfidenceLevel.LOW
        return data
