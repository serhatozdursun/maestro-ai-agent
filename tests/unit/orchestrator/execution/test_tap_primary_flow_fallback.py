"""``tap_on`` then ``run_flow`` fallback for tap execution."""

from __future__ import annotations

import time

from maestro_ai_agent.domain.enums import Platform, SelectorType
from maestro_ai_agent.orchestrator.execution.tap_primary_flow_fallback import (
    BLOCKER_POPUP_POST_TAP_SETTLE_S,
    execute_tap_primary_then_flow_fallback,
)
from maestro_ai_agent.services.maestro.hierarchy_csv import parse_maestro_hierarchy_csv
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


class _BaseProvider:
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def input_text(self, *, text: str, device_id: str | None = None):
        raise NotImplementedError

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


class _TextFallbackProvider(_BaseProvider):
    def __init__(self, *, csv: str) -> None:
        self._csv = csv
        self.tap_calls: list[tuple[str | None, str | None]] = []
        self.run_flow_calls: list[str] = []

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        return self._csv

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        self.tap_calls.append((tap_id, tap_text))
        return ActionResult(ok=True, message=None)

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        return ActionResult(ok=True, message=None)


def test_text_tap_no_ui_change_skips_run_flow_for_scenario_taps() -> None:
    """Scenario path: ok ``tap_on`` with unchanged hierarchy does not escalate the same selector."""
    csv = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _TextFallbackProvider(csv=csv)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(csv)
    out = execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="test",
        blocker_popup_fast_fallback=False,
    )
    assert out.terminal_ok is False
    assert out.winning_tool is None
    assert out.skipped_run_flow_escalation is True
    assert out.post_direct_outcome == "no_effect"
    assert p.run_flow_calls == []


def test_id_tap_triggers_run_flow_fallback_yaml_shape_under_blocker_fast_path() -> None:
    """Blocker dismissal keeps ``run_flow`` escalation when hierarchy is unchanged after tap."""
    csv = '1,0,"resource-id=a:id; class=android.view.View",\n'
    p = _TextFallbackProvider(csv=csv)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(csv)
    out = execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id="bag",
        tap_text=None,
        selector_type=SelectorType.ID,
        expression="id:bag",
        log_event_prefix="test",
        blocker_popup_fast_fallback=True,
    )
    assert out.terminal_ok is True
    assert out.winning_tool == "run_flow"
    yml = p.run_flow_calls[0]
    assert "appId: com.example.app" in yml
    assert "bag" in yml


def test_run_flow_failure_reports_terminal_not_ok() -> None:
    class _BadRun(_TextFallbackProvider):
        def tap_on(
            self,
            *,
            tap_id: str | None = None,
            tap_text: str | None = None,
            device_id: str | None = None,
        ) -> ActionResult:
            self.tap_calls.append((tap_id, tap_text))
            return ActionResult(ok=False, message="tap failed")

        def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
            self.run_flow_calls.append(flow_yaml)
            return ActionResult(ok=False, message="failed")

    csv = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _BadRun(csv=csv)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(csv)
    out = execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="test",
    )
    assert out.terminal_ok is False
    assert out.winning_tool is None
    assert len(p.run_flow_calls) == 1


def test_meaningful_hierarchy_change_skips_run_flow() -> None:
    """When ``tap_on`` changes the tree, fallback must not run."""

    class _TwoFrameProvider(_TextFallbackProvider):
        def __init__(self, *, before: str, after: str) -> None:
            super().__init__(csv=before)
            self._before = before
            self._after = after
            self._round = 0

        def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
            self._round += 1
            if self.tap_calls:
                return self._after
            return self._before

    before = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    after = '1,0,"text=Done; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _TwoFrameProvider(before=before, after=after)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(before)
    out = execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="test",
    )
    assert out.terminal_ok is True
    assert out.winning_tool == "tap_on"
    assert p.run_flow_calls == []


def test_blocker_popup_fast_fallback_skips_settle_when_tap_provider_fails(monkeypatch) -> None:
    class _TapFail(_TextFallbackProvider):
        def tap_on(
            self,
            *,
            tap_id: str | None = None,
            tap_text: str | None = None,
            device_id: str | None = None,
        ) -> ActionResult:
            self.tap_calls.append((tap_id, tap_text))
            return ActionResult(ok=False, message="tap failed")

    sleeps: list[float] = []

    def _record_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(time, "sleep", _record_sleep)
    csv = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _TapFail(csv=csv)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(csv)
    out = execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="popup",
        blocker_popup_fast_fallback=True,
    )
    assert sleeps == []
    assert out.terminal_ok is True
    assert out.winning_tool == "run_flow"


def test_blocker_popup_fast_fallback_applies_short_settle(monkeypatch) -> None:
    sleeps: list[float] = []

    def _record_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(time, "sleep", _record_sleep)
    csv = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _TextFallbackProvider(csv=csv)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(csv)
    out = execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="popup",
        blocker_popup_fast_fallback=True,
    )
    assert out.terminal_ok is True
    assert sleeps == [BLOCKER_POPUP_POST_TAP_SETTLE_S]


def test_default_tap_path_does_not_sleep_before_post_tap_observe(monkeypatch) -> None:
    sleeps: list[float] = []

    def _record_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr(time, "sleep", _record_sleep)
    csv = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _TextFallbackProvider(csv=csv)
    screen = MaestroScreenService(p)
    h = parse_maestro_hierarchy_csv(csv)
    execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="scenario_tap",
        blocker_popup_fast_fallback=False,
    )
    assert sleeps == []


class _RecordingScreen(MaestroScreenService):
    """Record ``include_screenshot`` for each ``observe_current_screen`` call."""

    def __init__(self, provider: _TextFallbackProvider) -> None:
        super().__init__(provider)
        self.observe_screenshot_flags: list[bool] = []

    def observe_current_screen(self, **kwargs: object) -> object:
        self.observe_screenshot_flags.append(bool(kwargs.get("include_screenshot")))
        return super().observe_current_screen(**kwargs)


def test_blocker_popup_fast_fallback_first_post_tap_observe_skips_screenshot() -> None:
    csv = '1,0,"text=Cart; class=android.widget.Button; bounds=[0,0][10,10]",\n'
    p = _TextFallbackProvider(csv=csv)
    screen = _RecordingScreen(p)
    h = parse_maestro_hierarchy_csv(csv)
    execute_tap_primary_then_flow_fallback(
        screen,
        app_id="com.example.app",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=True,
        hierarchy_before=h,
        tap_id=None,
        tap_text="Cart",
        selector_type=SelectorType.TEXT,
        expression="text:Cart",
        log_event_prefix="popup",
        blocker_popup_fast_fallback=True,
    )
    assert screen.observe_screenshot_flags[0] is False
    assert screen.observe_screenshot_flags[1] is True
