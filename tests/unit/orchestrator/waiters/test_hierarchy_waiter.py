"""Unit tests for hierarchy stability waiter (mocked observations)."""

from __future__ import annotations

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.hierarchy import HierarchyNode, HierarchySnapshot
from maestro_ai_agent.orchestrator.waiters.hierarchy_waiter import (
    hierarchy_stability_fingerprint,
    wait_for_hierarchy_stable,
)
from maestro_ai_agent.services.maestro.models import StructuredScreenObservation


def _node(
    *,
    idx: str,
    text: str | None = None,
    resource_id: str | None = None,
    class_name: str | None = "android.view.View",
) -> HierarchyNode:
    return HierarchyNode(
        node_index=idx,
        depth=0,
        parent_index=None,
        text=text,
        resource_id=resource_id,
        class_name=class_name,
    )


def _snap(nodes: list[HierarchyNode]) -> HierarchySnapshot:
    return HierarchySnapshot(nodes=nodes)


class _MockScreen:
    def __init__(self, snapshots: list[HierarchySnapshot]) -> None:
        self._queue = list(snapshots)
        self.observe_calls = 0

    def observe_current_screen(
        self,
        *,
        app_id: str,
        platform: Platform,
        device_id: str | None = None,
        include_screenshot: bool = False,
    ) -> StructuredScreenObservation:
        self.observe_calls += 1
        if not self._queue:
            msg = "test mock ran out of hierarchy snapshots"
            raise RuntimeError(msg)
        h = self._queue.pop(0)
        return StructuredScreenObservation(
            app_id=app_id,
            platform=platform,
            device_id=device_id,
            hierarchy=h,
            screenshot=None,
        )


def test_hierarchy_stability_fingerprint_is_deterministic() -> None:
    a = _snap([_node(idx="0", text="A", resource_id="rid", class_name="T")])
    b = _snap([_node(idx="0", text="A", resource_id="rid", class_name="T")])
    assert hierarchy_stability_fingerprint(a) == hierarchy_stability_fingerprint(b)


def test_wait_for_hierarchy_stable_exits_after_two_unchanged_polls() -> None:
    splash = _snap([_node(idx="0", text="Splash", resource_id=None)])
    mid = _snap([_node(idx="0", text="Loading", resource_id="p1")])
    home = _snap(
        [
            _node(idx="0", text="Home", resource_id="home", class_name="FrameLayout"),
            _node(idx="1", text="Shop", resource_id="shop", class_name="Button"),
        ],
    )
    # Initial splash, transitions, then three identical "home" frames so two polls match in a row.
    screen = _MockScreen([splash, mid, home, home, home])
    sleeps: list[float] = []

    def _sleep(d: float) -> None:
        sleeps.append(d)

    out = wait_for_hierarchy_stable(
        screen,
        "dev",
        "com.example",
        Platform.ANDROID,
        initial_delay_s=0.0,
        poll_interval_s=2.0,
        max_iterations=10,
        max_total_wait_s=20.0,
        sleep_fn=_sleep,
        monotonic_fn=lambda: 0.0,
    )
    assert out.screen_stable is True
    assert out.reason == "stable_twice"
    assert out.iterations_run == 4
    assert out.final_node_count == 2
    assert screen.observe_calls == 5
    assert sleeps == [2.0, 2.0, 2.0, 2.0]


def test_wait_for_hierarchy_stable_max_iterations_when_always_changing() -> None:
    seq = [
        _snap([_node(idx="0", text=f"v{i}")]) for i in range(20)
    ]  # 1 initial + 10 polls (mock has extra; unused)
    screen = _MockScreen(seq)

    out = wait_for_hierarchy_stable(
        screen,
        "dev",
        "com.example",
        Platform.IOS,
        initial_delay_s=0.0,
        poll_interval_s=0.01,
        max_iterations=10,
        max_total_wait_s=60.0,
        sleep_fn=lambda _d: None,
        monotonic_fn=lambda: 0.0,
    )
    assert out.screen_stable is False
    assert out.reason == "max_iterations"
    assert out.iterations_run == 10
    assert screen.observe_calls == 11
