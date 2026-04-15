"""Build observation cycle results from structured screen payloads."""

from __future__ import annotations

from maestro_ai_agent.orchestrator.models import ObservationCycleResult
from maestro_ai_agent.services.maestro.models import StructuredScreenObservation


def build_observation_cycle_result(
    structured: StructuredScreenObservation,
) -> ObservationCycleResult:
    """Normalize a service-layer observation into orchestrator runtime state."""
    return ObservationCycleResult(
        hierarchy=structured.hierarchy,
        parse_warnings=list(structured.hierarchy.parse_warnings),
        retrieved_at=structured.retrieved_at,
        app_id=structured.app_id,
        platform=structured.platform,
        device_id=structured.device_id,
        screenshot=structured.screenshot,
    )
