"""Scenario-run abort path when a blocking popup cannot be verified dismissed."""

from __future__ import annotations

import json
from pathlib import Path

from maestro_ai_agent.app.exploration_report import EXPLORATION_REPORT_FILENAME
from maestro_ai_agent.app.scenario_run import (
    MAESTRO_DRAFT_PREVIEW_FILENAME,
    ScenarioRunBlockingPopupError,
    _write_blocking_popup_failure_artifacts,
)
from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.orchestrator.waiters.hierarchy_waiter import HierarchyStableWaitOutcome
from maestro_ai_agent.services.maestro.blocking_popup_dismissal import KnownBlockingPopupOutcome


def test_scenario_run_blocking_popup_error_type() -> None:
    assert issubclass(ScenarioRunBlockingPopupError, RuntimeError)


def test_write_blocking_popup_failure_artifacts_writes_exploration_report(tmp_path: Path) -> None:
    popup = KnownBlockingPopupOutcome(
        handled=False,
        pattern_id="developer_mode_continue",
        reason="developer_mode_continue_still_visible_after_tap",
        should_abort_run=True,
        popup_tool_name="tap_on",
        popup_tool_args={"text": "Continue", "device_id": "d1", "deviceId": "d1"},
        tap_selector_basis="text",
    )
    wait = HierarchyStableWaitOutcome(
        screen_stable=True,
        iterations_run=2,
        final_node_count=10,
        reason="stable",
    )
    _write_blocking_popup_failure_artifacts(
        output_dir=tmp_path,
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="d1",
        popup_outcome=popup,
        initial_delay_before_stability_s=1.0,
        wait_outcome=wait,
    )
    data = json.loads((tmp_path / EXPLORATION_REPORT_FILENAME).read_text(encoding="utf-8"))
    assert data["orchestrator_ran"] is False
    assert data["preflight"]["popup_outcome"]["should_abort_run"] is True
    yaml = (tmp_path / MAESTRO_DRAFT_PREVIEW_FILENAME).read_text(encoding="utf-8")
    assert "blocking" in yaml.lower()
