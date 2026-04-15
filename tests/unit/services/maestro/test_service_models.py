"""Validation tests for Maestro service models."""

import pytest
from pydantic import ValidationError

from maestro_ai_agent.services.maestro.device_payload import parse_device_list_text
from maestro_ai_agent.services.maestro.models import (
    ActionRequest,
    DeviceInfo,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.transport_types import MaestroIntegrationError


def test_device_info_accepts_alias_id() -> None:
    device = DeviceInfo.model_validate({"id": "abc", "name": "Pixel"})
    assert device.device_id == "abc"
    assert device.description == "Pixel"


def test_device_info_rejects_missing_id() -> None:
    with pytest.raises(ValidationError):
        DeviceInfo.model_validate({"name": "only"})


def test_parse_device_list_text_invalid_json_raises() -> None:
    with pytest.raises(MaestroIntegrationError):
        parse_device_list_text("not-json")


def test_parse_device_list_text_unexpected_shape_raises() -> None:
    with pytest.raises(MaestroIntegrationError):
        parse_device_list_text('{"foo": 1}')


def test_screenshot_artifact_byte_length_non_negative() -> None:
    with pytest.raises(ValidationError):
        ScreenshotArtifact(byte_length=-1)


def test_action_request_requires_name() -> None:
    with pytest.raises(ValidationError):
        ActionRequest(name="")


def test_provider_capabilities_defaults() -> None:
    caps = ProviderCapabilities()
    assert caps.supports_take_screenshot is True
    assert caps.supports_inspect_view_hierarchy is True
