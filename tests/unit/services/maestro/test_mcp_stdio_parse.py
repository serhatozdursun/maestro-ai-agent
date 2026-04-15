"""Tests for MCP stdio response parsing (no subprocess)."""

from __future__ import annotations

from maestro_ai_agent.services.maestro.mcp_stdio_transport import mcp_tools_call_result_to_tool_call


def test_tools_call_success_maps_text_content() -> None:
    r = mcp_tools_call_result_to_tool_call(
        "inspect_view_hierarchy",
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "content": [{"type": "text", "text": "1,0,attrs,\n"}],
                "isError": False,
            },
        },
    )
    assert r.is_error is False
    assert "1,0" in r.text


def test_tools_call_is_error_maps_text() -> None:
    r = mcp_tools_call_result_to_tool_call(
        "tap_on",
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": "element not found"}],
                "isError": True,
            },
        },
    )
    assert r.is_error is True
    assert "element not found" in r.text


def test_json_rpc_error_field() -> None:
    r = mcp_tools_call_result_to_tool_call(
        "tap_on",
        {"jsonrpc": "2.0", "id": 4, "error": {"code": -1, "message": "boom"}},
    )
    assert r.is_error is True
    assert "boom" in r.text
