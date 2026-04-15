"""Known blocking popup dismissal (Developer Mode + Continue)."""

from __future__ import annotations

from maestro_ai_agent.app.maestro_draft_preview import build_blocking_popup_optional_tap_yaml_lines
from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.services.maestro.blocking_popup_dismissal import (
    PATTERN_DEVELOPER_MODE_CONTINUE,
    dismiss_known_blocking_popups_if_present,
)
from maestro_ai_agent.services.maestro.models import (
    ActionResult,
    ProviderCapabilities,
    ScreenshotArtifact,
)
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


def _csv_dev_mode_with_continue() -> str:
    return (
        '1,0,"text=Developer Mode; class=android.widget.TextView; bounds=[0,0][200,40]",\n'
        '2,0,"text=Restart; class=android.widget.Button; bounds=[0,50][100,80]",\n'
        '3,0,"text=Continue; class=android.widget.Button; bounds=[110,50][210,80]",\n'
    )


def _csv_plain_home() -> str:
    return '1,0,"text=Home; class=android.widget.TextView; bounds=[0,0][100,40]",\n'


def _csv_dev_mode_no_continue() -> str:
    return (
        '1,0,"text=Developer Mode; class=android.widget.TextView; bounds=[0,0][200,40]",\n'
        '2,0,"text=Restart; class=android.widget.Button; bounds=[0,50][100,80]",\n'
    )


class _PopupProvider:
    def __init__(self, *, csv: str, tap_ok: bool = True) -> None:
        self._csv = csv
        self.tap_ok = tap_ok
        self.tap_calls: list[tuple[str | None, str | None, str | None]] = []
        self.run_flow_calls: list[str] = []
        self.inspect_count = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_count += 1
        return self._csv

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        return ScreenshotArtifact(byte_length=0)

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        self.tap_calls.append((tap_id, tap_text, device_id))
        if not self.tap_ok:
            return ActionResult(ok=False, message="tap failed")
        return ActionResult(ok=True, message=None)

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        return ActionResult(ok=False, message="run_flow failed")

    def input_text(self, *, text: str, device_id: str | None = None):
        raise NotImplementedError

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


class _PopupClearsHierarchyAfterTap(_PopupProvider):
    """Direct ``tap_on`` alone dismisses the dialog (no ``run_flow`` needed)."""

    def __init__(self, *, dialog_csv: str, home_csv: str, tap_ok: bool = True) -> None:
        super().__init__(csv=dialog_csv, tap_ok=tap_ok)
        self._home_csv = home_csv
        self._post_tap = False

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_count += 1
        return self._home_csv if self._post_tap else self._csv

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        out = super().tap_on(tap_id=tap_id, tap_text=tap_text, device_id=device_id)
        if out.ok:
            self._post_tap = True
        return out

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        return ActionResult(ok=True, message=None)


class _DismissViaRunFlow(_PopupProvider):
    """``tap_on`` leaves hierarchy unchanged; ``run_flow`` clears the dialog."""

    def __init__(self, *, dialog_csv: str, home_csv: str) -> None:
        super().__init__(csv=dialog_csv, tap_ok=True)
        self._home = home_csv
        self._cleared = False

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        self.inspect_count += 1
        return self._home if self._cleared else self._csv

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        self._cleared = True
        return ActionResult(ok=True, message=None)


def test_known_popup_resolves_via_run_flow_when_tap_ineffective() -> None:
    p = _DismissViaRunFlow(
        dialog_csv=_csv_dev_mode_with_continue(),
        home_csv=_csv_plain_home(),
    )
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.kurtgeiger.kurtgeiger",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is True
    assert out.should_abort_run is False
    assert out.pattern_id == PATTERN_DEVELOPER_MODE_CONTINUE
    assert p.tap_calls == [(None, "Continue", "d1")]
    assert len(p.run_flow_calls) == 1
    yml = p.run_flow_calls[0]
    assert "appId: com.kurtgeiger.kurtgeiger" in yml
    assert "Continue" in yml
    assert out.popup_tool_name == "run_flow"
    assert out.tap_selector_basis == "text"
    assert out.dismiss_tap_text == "Continue"
    assert out.dismiss_tap_id is None


def test_popup_dismissed_by_tap_on_only_when_hierarchy_changes() -> None:
    p = _PopupClearsHierarchyAfterTap(
        dialog_csv=_csv_dev_mode_with_continue(),
        home_csv=_csv_plain_home(),
    )
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is True
    assert p.run_flow_calls == []
    assert out.popup_tool_name == "tap_on"
    assert out.dismiss_tap_text == "Continue"
    assert out.dismiss_tap_id is None


def test_popup_not_present_no_tap() -> None:
    p = _PopupProvider(csv=_csv_plain_home())
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is False
    assert out.should_abort_run is False
    assert out.pattern_id is None
    assert p.tap_calls == []
    assert p.run_flow_calls == []
    assert out.popup_tool_args is None
    assert out.dismiss_tap_text is None
    assert out.dismiss_tap_id is None
    ep = out.blocker_episode_dict()
    assert ep["detected"] is False
    assert ep["execution_attempted"] is False
    assert ep["code"] == "no_known_blocking_pattern"


def test_developer_mode_dismisses_next_label_instead_of_continue() -> None:
    csv = (
        '1,0,"text=Developer Mode; class=android.widget.TextView; bounds=[0,0][200,40]",\n'
        '2,0,"text=Next; class=android.widget.Button; bounds=[110,50][210,80]",\n'
    )
    p = _PopupClearsHierarchyAfterTap(
        dialog_csv=csv,
        home_csv=_csv_plain_home(),
    )
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is True
    assert p.tap_calls == [(None, "Next", "d1")]
    assert out.dismiss_tap_text == "Next"
    assert out.dismiss_tap_id is None
    assert out.dismiss_choice_reason is not None
    assert "prefer_text" in (out.dismiss_choice_reason or "")


def test_developer_mode_prefers_id_when_single_distinct_resource_id() -> None:
    csv = (
        '1,0,"text=Developer Mode; class=android.widget.TextView",\n'
        '2,0,"text=Allow; resource-id=com.example:id/dlg_allow; class=android.widget.Button",\n'
    )
    p = _PopupClearsHierarchyAfterTap(
        dialog_csv=csv,
        home_csv=_csv_plain_home(),
    )
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is True
    assert p.tap_calls[0][0] == "com.example:id/dlg_allow"
    assert p.tap_calls[0][1] is None
    assert out.dismiss_tap_id == "com.example:id/dlg_allow"
    assert out.tap_selector_basis == "id"
    assert out.dismiss_choice_reason is not None
    assert "prefer_id" in (out.dismiss_choice_reason or "")
    yaml_lines = build_blocking_popup_optional_tap_yaml_lines(
        handled=out.handled,
        tap_selector_basis=out.tap_selector_basis,
        dismiss_tap_text=out.dismiss_tap_text,
        dismiss_tap_id=out.dismiss_tap_id,
    )
    joined = "\n".join(yaml_lines)
    assert "com.example:id/dlg_allow" in joined
    assert "optional: true" in joined


def test_tracking_keyword_with_allow_dismiss() -> None:
    csv = (
        '1,0,"text=We use tracking; class=android.widget.TextView",\n'
        '2,0,"text=Allow; class=android.widget.Button",\n'
    )
    p = _PopupClearsHierarchyAfterTap(dialog_csv=csv, home_csv=_csv_plain_home())
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is True
    assert out.pattern_id == "tracking_prompt"
    assert p.tap_calls == [(None, "Allow", "d1")]


def test_keyword_without_allowlist_no_dismiss() -> None:
    csv = '1,0,"text=We use tracking; class=android.widget.TextView",\n'
    p = _PopupProvider(csv=csv)
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is False
    assert out.pattern_id is None
    assert p.tap_calls == []


def test_blocker_detected_dismiss_unresolved_custom_pattern() -> None:
    """Pattern matches hierarchy but returns no dismiss action → abort."""

    class _Unresolvable:
        pattern_id = "test_unresolvable"

        def detect(self, hierarchy) -> bool:
            from maestro_ai_agent.domain.dialog_signals import text_substring_present

            return text_substring_present(hierarchy, "ZZBLOCKERZZ")

        def resolve_dismiss(self, hierarchy):
            return None

        def verify_cleared(self, hierarchy) -> bool:
            return True

    csv = '1,0,"text=ZZBLOCKERZZ; class=android.widget.TextView",\n'
    p = _PopupProvider(csv=csv)
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
        patterns=[_Unresolvable()],
    )
    assert out.handled is False
    assert out.should_abort_run is True
    assert out.pattern_id == "test_unresolvable"
    assert out.reason == "blocker_detected_dismiss_unresolved"
    ep = out.blocker_episode_dict()
    assert ep["detected"] is True
    assert ep["dismiss_action"] is None
    assert ep["abort_reason"] == "blocker_detected_dismiss_unresolved"


def test_developer_mode_without_continue_no_tap_warning_only() -> None:
    p = _PopupProvider(csv=_csv_dev_mode_no_continue())
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is False
    assert out.should_abort_run is False
    assert out.pattern_id == PATTERN_DEVELOPER_MODE_CONTINUE
    assert "allowlist" in out.reason.lower()
    assert p.tap_calls == []


def test_tap_and_run_flow_fail_aborts() -> None:
    p = _PopupProvider(csv=_csv_dev_mode_with_continue(), tap_ok=False)
    svc = MaestroScreenService(p)
    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is False
    assert out.should_abort_run is True
    assert out.pattern_id == PATTERN_DEVELOPER_MODE_CONTINUE
    assert out.reason == "tap_primary_flow_fallback_failed"
    assert len(p.tap_calls) == 1
    assert len(p.run_flow_calls) == 1
    assert out.dismiss_tap_text == "Continue"
    assert out.dismiss_tap_id is None
    ep = out.blocker_episode_dict()
    assert ep["execution_result"] is not None
    assert ep["execution_result"]["ok"] is False
    assert ep["verified_cleared"] is None


class _StuckDialogAfterRunFlow(_PopupProvider):
    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        self.run_flow_calls.append(flow_yaml)
        return ActionResult(ok=True, message=None)


def test_dialog_still_visible_after_run_flow_aborts() -> None:
    p = _StuckDialogAfterRunFlow(csv=_csv_dev_mode_with_continue(), tap_ok=True)
    svc = MaestroScreenService(p)

    out = dismiss_known_blocking_popups_if_present(
        svc,
        device_id="d1",
        app_id="com.example",
        platform=Platform.ANDROID,
        include_screenshot=False,
    )
    assert out.handled is False
    assert out.should_abort_run is True
    assert out.reason == "blocker_still_detected_after_dismiss"
    assert p.tap_calls == [(None, "Continue", "d1")]
    assert len(p.run_flow_calls) == 1
    assert p.inspect_count >= 2
    assert out.dismiss_tap_text == "Continue"
    assert out.dismiss_tap_id is None
    ep = out.blocker_episode_dict()
    assert ep["verified_cleared"] is False
    assert ep["execution_result"] is not None
    assert ep["execution_result"]["ok"] is True
