"""Best-effort parsing of Maestro ``list_devices`` tool output."""

from __future__ import annotations

import json

from maestro_ai_agent.services.maestro.models import DeviceInfo
from maestro_ai_agent.services.maestro.transport_types import MaestroIntegrationError


def parse_device_list_text(text: str) -> list[DeviceInfo]:
    """
    Parse JSON emitted by Maestro's ``list_devices`` MCP tool.

    Maestro versions may return either a bare JSON array or an object wrapper; this parser
    accepts a small set of shapes and fails loudly otherwise.
    """
    stripped = text.strip()
    if not stripped:
        return []

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise MaestroIntegrationError(
            "list_devices response was not valid JSON",
            details={"snippet": stripped[:200]},
        ) from exc

    if isinstance(payload, list):
        return [DeviceInfo.model_validate(item) for item in payload]

    if isinstance(payload, dict):
        for key in ("devices", "deviceList", "items"):
            maybe_list = payload.get(key)
            if isinstance(maybe_list, list):
                return [DeviceInfo.model_validate(item) for item in maybe_list]

    raise MaestroIntegrationError(
        "Unexpected list_devices JSON shape",
        details={"snippet": stripped[:200]},
    )
