"""Port for optional screenshot-backed target suggestions (hierarchy remains primary)."""

from __future__ import annotations

from typing import Protocol

from maestro_ai_agent.domain.visual_advisory import VisualAdvisoryRequest, VisualAdvisoryResponse


class VisualTargetSuggester(Protocol):
    """Advisory backend (e.g. multimodal LLM); must never replace hierarchy-first ranking."""

    def suggest(self, request: VisualAdvisoryRequest) -> VisualAdvisoryResponse | None:
        """Return structured hints or ``None`` to skip (low confidence, refusal, etc.)."""
        ...


class NullVisualTargetSuggester:
    """Default no-op implementation (always declines)."""

    def suggest(self, _request: VisualAdvisoryRequest) -> VisualAdvisoryResponse | None:
        return None
