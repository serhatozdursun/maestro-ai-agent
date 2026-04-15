"""
Minimal MCP client over stdio (newline-delimited JSON) for a single Maestro MCP process.

MCP stdio uses **one UTF-8 JSON-RPC object per line** (see MCP transport docs). Some stacks
also support ``Content-Length`` framing; Maestro's ``maestro mcp`` server expects **NDJSON**
lines, which is why this client uses line framing—not HTTP-style headers.

Spike / integration use only: not a general MCP SDK. Implements ``MaestroToolTransport``.
"""

from __future__ import annotations

import base64
import contextlib
import json
import select
import shlex
import subprocess
import sys
import threading
from collections.abc import Mapping
from typing import Any

from maestro_ai_agent.services.maestro.transport_types import ToolCallResult
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)


def mcp_tools_call_result_to_tool_call(name: str, rpc_message: dict[str, Any]) -> ToolCallResult:
    """Map a JSON-RPC response for ``tools/call`` to :class:`ToolCallResult` (unit-tested)."""
    if "error" in rpc_message:
        err = rpc_message["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return ToolCallResult(tool_name=name, text=msg, is_error=True, raw=rpc_message)

    result = rpc_message.get("result")
    if not isinstance(result, dict):
        return ToolCallResult(
            tool_name=name,
            text="Unexpected tools/call payload (missing result dict).",
            is_error=True,
            raw=rpc_message,
        )

    if result.get("isError"):
        parts: list[str] = []
        for block in result.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return ToolCallResult(
            tool_name=name,
            text="\n".join(parts).strip() or "Tool returned isError without text.",
            is_error=True,
            raw=rpc_message,
        )

    text_chunks: list[str] = []
    binary: list[bytes] = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text_chunks.append(str(block.get("text", "")))
        elif btype == "image":
            data = block.get("data")
            if isinstance(data, str):
                with contextlib.suppress(ValueError, TypeError):
                    binary.append(base64.b64decode(data))
        elif btype == "resource":
            res = block.get("resource")
            if isinstance(res, dict) and isinstance(res.get("text"), str):
                text_chunks.append(res["text"])

    return ToolCallResult(
        tool_name=name,
        text="".join(text_chunks),
        binary=binary,
        is_error=False,
        raw=rpc_message,
    )


class McpStdioTransport:
    """
    Run ``argv`` (default ``maestro mcp``) and speak MCP JSON-RPC as **NDJSON** on stdin/stdout.

    Linux/macOS: uses ``select`` read timeouts. Windows: blocking reads (no timeout).
    """

    def __init__(
        self,
        argv: list[str] | None = None,
        *,
        protocol_version: str = "2024-11-05",
        read_timeout_s: float = 120.0,
    ) -> None:
        self._argv = argv if argv is not None else ["maestro", "mcp"]
        self._protocol_version = protocol_version
        self._read_timeout_s = read_timeout_s
        self._proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None

    @classmethod
    def from_shell_command(cls, command: str, **kwargs: Any) -> McpStdioTransport:
        """Parse a shell-style command (e.g. ``maestro mcp``) into argv."""
        parts = shlex.split(command.strip())
        if not parts:
            msg = "mcp command must not be empty"
            raise ValueError(msg)
        return cls(parts, **kwargs)

    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            self._argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self._proc.stderr is not None

        def _drain_stderr(stream: Any) -> None:
            for line in stream:
                if isinstance(line, bytes):
                    self._stderr_lines.append(line.decode("utf-8", errors="replace").rstrip("\n"))
                else:
                    self._stderr_lines.append(str(line).rstrip("\n"))

        t = threading.Thread(
            target=_drain_stderr,
            args=(self._proc.stderr,),
            name="mcp-stderr",
            daemon=True,
        )
        t.start()
        self._stderr_thread = t
        log.info("mcp_subprocess_started", argv=list(self._argv))

        init_id = self._next_id
        self._next_id += 1
        self._send_json(
            {
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": self._protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": "maestro-ai-agent-scenario", "version": "0.1.0"},
                },
            },
        )
        log.info("mcp_initialize_sent", jsonrpc_id=init_id, protocol=self._protocol_version)
        init_msg = self._read_until_response_id(init_id)
        if "error" in init_msg:
            err = init_msg["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            self.stop()
            raise RuntimeError(f"MCP initialize failed: {msg}")
        log.info("mcp_initialize_ok", jsonrpc_id=init_id)

        self._send_json(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        log.info("mcp_initialized_notification_sent")

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        if proc.stdin:
            with contextlib.suppress(BrokenPipeError):
                proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolCallResult:
        if self._proc is None:
            msg = "McpStdioTransport.start() must be called before call_tool."
            raise RuntimeError(msg)
        req_id = self._next_id
        self._next_id += 1
        self._send_json(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            },
        )
        log.debug("mcp_tools_call_sent", tool=name, jsonrpc_id=req_id)
        msg = self._read_until_response_id(req_id)
        return mcp_tools_call_result_to_tool_call(name, msg)

    def _send_json(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("MCP process not started")
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        proc.stdin.write(line.encode("utf-8"))
        proc.stdin.flush()

    def _readline_raw(self) -> bytes:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise RuntimeError("MCP process not started")
        stdout = proc.stdout
        fileno = stdout.fileno()
        if sys.platform == "win32":
            return stdout.readline()
        ready, _, _ = select.select([fileno], [], [], self._read_timeout_s)
        if not ready:
            hint = "; ".join(self._stderr_lines[-8:]) if self._stderr_lines else ""
            extra = f" stderr_tail={hint!r}" if hint else ""
            msg = f"MCP read timeout after {self._read_timeout_s}s{extra}"
            raise TimeoutError(msg)
        return stdout.readline()

    def _read_one_message(self) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise RuntimeError("MCP process not started")

        while True:
            line = self._readline_raw()
            if line == b"":
                tail = "\n".join(self._stderr_lines[-20:])
                raise EOFError(f"MCP stdout closed. stderr (last lines):\n{tail}")
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed: Any = json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError as e:
                preview = stripped[:200]
                err = f"Non-JSON MCP stdout line: {preview!r} ({e})"
                raise ValueError(err) from e
            if not isinstance(parsed, dict):
                err = f"MCP stdout JSON was not an object: {type(parsed).__name__}"
                raise TypeError(err)
            log.debug(
                "mcp_message_received",
                keys=list(parsed.keys()),
                jsonrpc_id=parsed.get("id"),
                method=parsed.get("method"),
            )
            return parsed

    def _read_until_response_id(self, want_id: int) -> dict[str, Any]:
        while True:
            msg = self._read_one_message()
            if msg.get("id") == want_id:
                return msg
            # Ignore server notifications and unrelated responses.

    def __enter__(self) -> McpStdioTransport:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop()
