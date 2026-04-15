"""Scenario-run preflight launch_app ordering (no MCP subprocess)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from maestro_ai_agent.app import scenario_run
from maestro_ai_agent.app.exploration_report import EXPLORATION_REPORT_FILENAME
from maestro_ai_agent.app.scenario_run import (
    ScenarioRunLaunchError,
    perform_device_preflight_launch,
    run_scenario_exploration,
)
from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.orchestrator.planning_service import ScenarioPlanningOrchestrator
from maestro_ai_agent.services.maestro.models import ActionResult, ScreenshotArtifact
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


class _OrderProvider:
    """Records call order; optional launch failure."""

    def __init__(self, *, launch_ok: bool = True) -> None:
        self.calls: list[str] = []
        self.launch_ok = launch_ok
        self.last_launch_permissions: Mapping[str, Any] | None = None

    def capabilities(self):
        raise NotImplementedError

    def list_devices(self):
        raise NotImplementedError

    def launch_app(
        self,
        *,
        app_id: str,
        device_id: str | None = None,
        permissions: Mapping[str, Any] | None = None,
    ) -> ActionResult:
        self.calls.append("launch_app")
        self.last_launch_permissions = permissions
        if not self.launch_ok:
            return ActionResult(ok=False, message="launch denied")
        return ActionResult(ok=True, message=None)

    def stop_app(self, *, app_id: str, device_id: str | None = None) -> ActionResult:
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.calls.append("inspect_view_hierarchy")
        return '1,0,"text=x; class=android.view.View",\n'

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        raise NotImplementedError

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        raise NotImplementedError

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        raise NotImplementedError

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        raise NotImplementedError

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


def test_launch_succeeds_then_hierarchy_is_requested() -> None:
    p = _OrderProvider(launch_ok=True)
    svc = MaestroScreenService(p)
    out = perform_device_preflight_launch(
        svc,
        app_id="com.example",
        device_id="dev-1",
    )
    assert out.ok is True
    assert p.calls == ["launch_app"]
    assert p.last_launch_permissions == {"all": "allow"}

    svc.observe_current_screen(
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="dev-1",
        include_screenshot=False,
    )
    assert p.calls == ["launch_app", "inspect_view_hierarchy"]


def test_run_scenario_exploration_launch_fails_hierarchy_not_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    orch_calls: list[str] = []

    def _fake_observe(self: ScenarioPlanningOrchestrator, request):
        orch_calls.append("run_observe_plan_execute")
        raise AssertionError("orchestrator must not run when launch fails")

    monkeypatch.setattr(
        ScenarioPlanningOrchestrator,
        "run_observe_plan_execute",
        _fake_observe,
    )

    def _fake_preflight(
        screen: MaestroScreenService,
        *,
        app_id: str,
        device_id: str,
    ) -> ActionResult:
        return ActionResult(ok=False, message="launch denied")

    monkeypatch.setattr(scenario_run, "perform_device_preflight_launch", _fake_preflight)

    class _DummyTransport:
        def __enter__(self) -> _DummyTransport:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def _fake_from_shell(cls, *args, **kwargs):
        return _DummyTransport()

    monkeypatch.setattr(
        scenario_run.McpStdioTransport,
        "from_shell_command",
        classmethod(_fake_from_shell),
    )

    with pytest.raises(ScenarioRunLaunchError, match="launch denied"):
        run_scenario_exploration(
            app_id="com.example",
            platform=Platform.IOS,
            scenario_text="Tap 'OK'",
            device_id="dev-1",
            output_dir=tmp_path,
            mcp_command="maestro mcp",
            post_launch_settle_s=0.0,
        )

    assert orch_calls == []
    er = tmp_path / EXPLORATION_REPORT_FILENAME
    assert er.is_file()
    payload = json.loads(er.read_text(encoding="utf-8"))
    assert payload["preflight"]["launch_ok"] is False
    assert payload["orchestrator_ran"] is False
