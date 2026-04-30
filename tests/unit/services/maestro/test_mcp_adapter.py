"""Tests for MCP adapter behavior with mocked transports."""

from collections.abc import Mapping
from typing import Any

import pytest

from maestro_ai_agent.services.maestro.mcp_adapter import (
    McpMaestroAdapter,
    inspect_screen_json_to_legacy_hierarchy_csv,
    run_flow_mcp_arguments,
    tap_on_mcp_arguments,
    tap_on_selector_basis,
)
from maestro_ai_agent.services.maestro.transport_types import (
    MaestroIntegrationError,
    ToolCallResult,
    TransportNotConfiguredError,
)
from maestro_ai_agent.services.maestro.transport_unconfigured import UnconfiguredMcpTransport


class RecordingTransport:
    """Minimal fake MCP transport for unit tests."""

    def __init__(self, mapping: dict[str, ToolCallResult]) -> None:
        self.mapping = mapping
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolCallResult:
        self.calls.append((name, dict(arguments)))
        if name not in self.mapping:
            msg = f"unexpected tool {name}"
            raise AssertionError(msg)
        return self.mapping[name]


class SequenceTransport:
    """Return queued results per tool call to test fallback flows."""

    def __init__(self, mapping: dict[str, list[ToolCallResult]]) -> None:
        self.mapping = {k: list(v) for k, v in mapping.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolCallResult:
        self.calls.append((name, dict(arguments)))
        queue = self.mapping.get(name)
        if not queue:
            msg = f"unexpected tool {name}"
            raise AssertionError(msg)
        return queue.pop(0)


def test_inspect_view_hierarchy_invokes_tool_and_returns_text() -> None:
    csv = '1,0,"resource-id=a:id; class=android.view.View; package=com.a",\n'
    transport = RecordingTransport(
        {
            "inspect_view_hierarchy": ToolCallResult(
                tool_name="inspect_view_hierarchy",
                text=csv,
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    assert adapter.inspect_view_hierarchy(device_id="dev-1") == csv
    assert transport.calls[0] == (
        "inspect_view_hierarchy",
        {"device_id": "dev-1", "deviceId": "dev-1"},
    )


def test_inspect_view_hierarchy_error_raises() -> None:
    transport = RecordingTransport(
        {
            "inspect_view_hierarchy": ToolCallResult(
                tool_name="inspect_view_hierarchy",
                text="boom",
                is_error=True,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    with pytest.raises(MaestroIntegrationError):
        adapter.inspect_view_hierarchy()


def test_launch_app_includes_permissions_in_mcp_payload_when_provided() -> None:
    transport = RecordingTransport(
        {
            "launch_app": ToolCallResult(
                tool_name="launch_app",
                text="ok",
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.launch_app(
        app_id="com.example",
        device_id="dev-1",
        permissions={"all": "allow"},
    )
    assert result.ok is True
    assert transport.calls[0][0] == "launch_app"
    args = transport.calls[0][1]
    assert args["appId"] == "com.example"
    assert args["permissions"] == {"all": "allow"}
    assert args["device_id"] == "dev-1"
    assert args["deviceId"] == "dev-1"


def test_launch_app_omits_permissions_key_when_not_provided() -> None:
    transport = RecordingTransport(
        {
            "launch_app": ToolCallResult(
                tool_name="launch_app",
                text="ok",
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    adapter.launch_app(app_id="com.example", device_id=None)
    assert "permissions" not in transport.calls[0][1]


def test_list_devices_json_array() -> None:
    payload = '[{"id": "emu-1", "name": "Emulator"}]'
    transport = RecordingTransport(
        {"list_devices": ToolCallResult(tool_name="list_devices", text=payload, is_error=False)}
    )
    adapter = McpMaestroAdapter(transport)
    devices = adapter.list_devices()
    assert len(devices) == 1
    assert devices[0].device_id == "emu-1"


def test_action_tools_return_action_result_on_error_flag() -> None:
    transport = RecordingTransport(
        {
            "tap_on": ToolCallResult(
                tool_name="tap_on",
                text="selector not found",
                is_error=True,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.tap_on(tap_text="Missing", device_id=None)
    assert result.ok is False
    assert "selector" in (result.message or "").lower()
    assert transport.calls[0][1]["text"] == "Missing"
    assert "selector" not in transport.calls[0][1]


def test_tap_on_sends_id_parameter() -> None:
    transport = RecordingTransport(
        {
            "tap_on": ToolCallResult(
                tool_name="tap_on",
                text="ok",
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.tap_on(tap_id="bag", device_id="dev-1")
    assert result.ok is True
    assert transport.calls[0] == (
        "tap_on",
        {"id": "bag", "device_id": "dev-1", "deviceId": "dev-1"},
    )


def test_run_flow_sends_flow_yaml_and_device() -> None:
    yml = "appId: com.example\n---\n- tapOn: OK"
    transport = RecordingTransport(
        {
            "run_flow": ToolCallResult(
                tool_name="run_flow",
                text="ok",
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.run_flow(flow_yaml=yml, device_id="dev-1")
    assert result.ok is True
    assert transport.calls[0] == (
        "run_flow",
        {"flow_yaml": yml, "device_id": "dev-1", "deviceId": "dev-1"},
    )


def test_run_flow_mcp_arguments_shape() -> None:
    args = run_flow_mcp_arguments(flow_yaml="appId: a\n---\n- tapOn: X", device_id="d1")
    assert args["flow_yaml"].startswith("appId:")
    assert args["device_id"] == "d1"


def test_tap_on_mcp_arguments_plain_text_continue_matches_popup_dismissal() -> None:
    payload = tap_on_mcp_arguments(tap_id=None, tap_text="Continue", device_id="d1")
    assert payload == {"text": "Continue", "device_id": "d1", "deviceId": "d1"}
    assert tap_on_selector_basis(payload) == "text"


def test_tap_on_sends_text_parameter() -> None:
    transport = RecordingTransport(
        {
            "tap_on": ToolCallResult(
                tool_name="tap_on",
                text="ok",
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.tap_on(tap_text="Cart", device_id=None)
    assert result.ok is True
    assert transport.calls[0] == ("tap_on", {"text": "Cart"})


def test_tap_on_without_id_or_text_does_not_call_transport() -> None:
    transport = RecordingTransport({})
    adapter = McpMaestroAdapter(transport)
    result = adapter.tap_on(device_id=None)
    assert result.ok is False
    assert "text" in (result.message or "").lower() and "id" in (result.message or "").lower()
    assert transport.calls == []


def test_check_flow_syntax_forwards_payload() -> None:
    transport = RecordingTransport(
        {
            "check_flow_syntax": ToolCallResult(
                tool_name="check_flow_syntax",
                text="ok",
                is_error=False,
            )
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.check_flow_syntax(flow_yaml="appId: demo\n---\n- launchApp")
    assert result.ok is True
    assert transport.calls[0][1]["flow"].startswith("appId")


def test_unconfigured_transport_raises() -> None:
    transport = UnconfiguredMcpTransport()
    adapter = McpMaestroAdapter(transport)
    with pytest.raises(TransportNotConfiguredError):
        adapter.inspect_view_hierarchy()


def test_launch_app_falls_back_to_run_when_legacy_tool_missing() -> None:
    transport = SequenceTransport(
        {
            "launch_app": [
                ToolCallResult(
                    tool_name="launch_app",
                    text="Tool launch_app not found",
                    is_error=True,
                )
            ],
            "run": [ToolCallResult(tool_name="run", text="ok", is_error=False)],
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.launch_app(app_id="com.example.demo", device_id="dev-1")
    assert result.ok is True
    assert transport.calls[0][0] == "launch_app"
    assert transport.calls[1][0] == "run"
    assert "launchApp" in str(transport.calls[1][1]["yaml"])


def test_inspect_view_hierarchy_falls_back_to_inspect_screen() -> None:
    transport = SequenceTransport(
        {
            "inspect_view_hierarchy": [
                ToolCallResult(
                    tool_name="inspect_view_hierarchy",
                    text="Tool inspect_view_hierarchy not found",
                    is_error=True,
                )
            ],
            "inspect_screen": [
                ToolCallResult(
                    tool_name="inspect_screen",
                    text='{"elements":{"txt":"Search","rid":"search_box","cls":"XCUIElementTypeButton","b":{"x":0,"y":0,"width":100,"height":50},"c":[]}}',
                    is_error=False,
                )
            ],
        }
    )
    adapter = McpMaestroAdapter(transport)
    csv_text = adapter.inspect_view_hierarchy(device_id="dev-1")
    assert "resource-id=search_box" in csv_text
    assert "text=Search" in csv_text
    assert "bounds=[0,0][100,50]" in csv_text


def test_tap_on_falls_back_to_run_when_legacy_tool_missing() -> None:
    transport = SequenceTransport(
        {
            "tap_on": [
                ToolCallResult(
                    tool_name="tap_on",
                    text="Tool tap_on not found",
                    is_error=True,
                )
            ],
            "run": [ToolCallResult(tool_name="run", text="ok", is_error=False)],
        }
    )
    adapter = McpMaestroAdapter(transport)
    result = adapter.tap_on(tap_text="Search", device_id="dev-1")
    assert result.ok is True
    assert transport.calls[1][0] == "run"
    assert "tapOn" in str(transport.calls[1][1]["yaml"])


def test_inspect_screen_converter_handles_list_roots() -> None:
    csv_text = inspect_screen_json_to_legacy_hierarchy_csv(
        '{"elements":[{"txt":"One","c":[]},{"txt":"Two","c":[]}]}'
    )
    assert "text=One" in csv_text
    assert "text=Two" in csv_text
