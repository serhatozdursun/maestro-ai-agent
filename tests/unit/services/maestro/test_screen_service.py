"""Tests for MaestroScreenService orchestration."""

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.services.maestro.models import ActionResult, ScreenshotArtifact
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService


class StubProvider:
    def __init__(self, *, csv: str, shot: ScreenshotArtifact | None) -> None:
        self._csv = csv
        self._shot = shot

    def capabilities(self):
        raise NotImplementedError

    def list_devices(self):
        raise NotImplementedError

    def launch_app(self, *, app_id: str, device_id: str | None = None, permissions=None):
        raise NotImplementedError

    def stop_app(self, *, app_id: str, device_id: str | None = None):
        raise NotImplementedError

    def inspect_view_hierarchy(self, *, device_id: str | None = None) -> str:
        assert device_id == "d1"
        return self._csv

    def take_screenshot(self, *, device_id: str | None = None) -> ScreenshotArtifact:
        assert device_id == "d1"
        assert self._shot is not None
        return self._shot

    def tap_on(
        self,
        *,
        tap_id: str | None = None,
        tap_text: str | None = None,
        device_id: str | None = None,
    ) -> ActionResult:
        return ActionResult(ok=False, message="stub")

    def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
        return ActionResult(ok=False, message="stub")

    def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
        return ActionResult(ok=False, message="stub")

    def check_flow_syntax(self, *, flow_yaml: str):
        raise NotImplementedError


def test_observe_current_screen_parses_hierarchy() -> None:
    csv = '1,0,"resource-id=a:id; class=android.view.View; package=com.a",\n'
    provider = StubProvider(csv=csv, shot=None)
    service = MaestroScreenService(provider)
    obs = service.observe_current_screen(
        app_id="com.example",
        platform=Platform.ANDROID,
        device_id="d1",
        include_screenshot=False,
    )
    assert obs.app_id == "com.example"
    assert obs.platform is Platform.ANDROID
    assert obs.device_id == "d1"
    assert len(obs.hierarchy.nodes) == 1
    assert obs.screenshot is None


def test_screen_service_forwards_run_flow_to_provider() -> None:
    class FlowProvider(StubProvider):
        def run_flow(self, *, flow_yaml: str, device_id: str | None = None) -> ActionResult:
            assert "tapOn" in flow_yaml
            return ActionResult(ok=True, message=None)

    csv = '1,0,"text=x; class=android.view.View",\n'
    provider = FlowProvider(csv=csv, shot=None)
    service = MaestroScreenService(provider)
    r = service.run_flow(flow_yaml="appId: a\n---\n- tapOn: OK", device_id="d1")
    assert r.ok is True


def test_screen_service_forwards_tap_and_input_to_provider() -> None:
    class TapProvider(StubProvider):
        def tap_on(
            self,
            *,
            tap_id: str | None = None,
            tap_text: str | None = None,
            device_id: str | None = None,
        ) -> ActionResult:
            return ActionResult(ok=True, message="tapped")

        def input_text(self, *, text: str, device_id: str | None = None) -> ActionResult:
            return ActionResult(ok=True, message="typed")

    csv = '1,0,"resource-id=a:id; class=android.view.View; package=com.a",\n'
    provider = TapProvider(csv=csv, shot=None)
    service = MaestroScreenService(provider)
    assert service.tap_on(tap_text="OK", device_id="d1").ok is True
    assert service.input_text(text="hi", device_id="d1").ok is True


def test_observe_current_screen_includes_screenshot_metadata() -> None:
    csv = '1,0,"resource-id=a:id; class=android.view.View; package=com.a",\n'
    shot = ScreenshotArtifact(byte_length=3, image_bytes=b"\x01\x02\x03")
    provider = StubProvider(csv=csv, shot=shot)
    service = MaestroScreenService(provider)
    obs = service.observe_current_screen(
        app_id="com.example",
        platform=Platform.IOS,
        device_id="d1",
        include_screenshot=True,
    )
    assert obs.screenshot is not None
    assert obs.screenshot.byte_length == 3
    assert obs.screenshot.image_bytes == b"\x01\x02\x03"
