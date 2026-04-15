"""
Optional AI-assisted normalization.

**Contract:** implementations may only return or adjust a :class:`CanonicalScenario`
(step ``action`` / ``target`` / ``value``). They must **not** emit Maestro YAML,
provider calls, or orchestration artifacts.
"""

from __future__ import annotations

from typing import Protocol

from maestro_ai_agent.scenario.canonical_model import CanonicalScenario
from maestro_ai_agent.scenario.classifier import ScenarioInputProfile


class AIFallbackParser(Protocol):
    """Port for a future LLM / rules hybrid that refines canonical steps only."""

    def normalize_to_canonical(
        self,
        *,
        text: str,
        profile: ScenarioInputProfile,
        draft: CanonicalScenario,
        confidence_reason: str,
    ) -> CanonicalScenario | None:
        """
        Return an improved canonical scenario, or ``None`` to keep the draft.

        Must not produce Maestro flows or device actions—canonical steps only.
        """
        ...


class NullAIFallbackParser:
    """Default no-op (always declines)."""

    def normalize_to_canonical(
        self,
        *,
        text: str,
        profile: ScenarioInputProfile,
        draft: CanonicalScenario,
        confidence_reason: str,
    ) -> CanonicalScenario | None:
        return None
