"""High-level screen observation API built on :class:`MaestroScreenProvider`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv
from maestro_ai_agent.services.maestro.models import ActionResult, StructuredScreenObservation
from maestro_ai_agent.services.maestro.ports import MaestroScreenProvider


class MaestroScreenService:
    """
    Facade for orchestrator-style screen reads.

    This service intentionally stays narrow: it composes hierarchy inspection (primary)
    with optional screenshots (secondary) and returns structured models.

    Tap / text-input helpers delegate to the same provider so the orchestrator can depend
    on one facade for observe + conservative execution (see ``orchestrator.execution``).
    """

    def __init__(self, provider: MaestroScreenProvider) -> None:
        self._provider = provider

    def launch_app(
        self,
        *,
        app_id: str,
        device_id: str | None = None,
        permissions: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        """Forward to the provider (optional ``permissions`` for Maestro ``launchApp``)."""
        return self._provider.launch_app(
            app_id=app_id,
            device_id=device_id,
            permissions=permissions,
        )

    def observe_current_screen(
        self,
        *,
        app_id: str,
        platform: Platform,
        device_id: str | None = None,
        include_screenshot: bool = False,
    ) -> StructuredScreenObservation:
        """
        Fetch the current hierarchy (CSV) and optionally a screenshot.

        ``app_id`` / ``platform`` are carried for traceability; Maestro tools may or may not
        consume them directly today. The hierarchy remains the primary structured signal.
        """
        csv_text = self._provider.inspect_view_hierarchy(device_id=device_id)
        hierarchy = parse_maestro_hierarchy_csv(csv_text)
        screenshot = None
        if include_screenshot:
            screenshot = self._provider.take_screenshot(device_id=device_id)
        return StructuredScreenObservation(
            app_id=app_id,
            platform=platform,
            device_id=device_id,
            hierarchy=hierarchy,
            screenshot=screenshot,
        )

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        """Forward structured Maestro tap targets to the provider."""
        return self._provider.tap_on(tap_id=tap_id, tap_text=tap_text, device_id=device_id)

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        """Run inline Maestro flow YAML (``tap_on`` fallback when direct tap is ineffective)."""
        return self._provider.run_flow(flow_yaml=flow_yaml, device_id=device_id)

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        """Forward to the provider; orchestrator supplies text only from scenario data."""
        return self._provider.input_text(text=text, device_id=device_id)
