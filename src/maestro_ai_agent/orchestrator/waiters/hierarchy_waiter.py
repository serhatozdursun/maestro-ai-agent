"""Poll hierarchy until fingerprint is unchanged across two consecutive samples."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot, effective_visible_text
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)

# Defaults aligned with device preflight / scenario-run hierarchy stability waits.
_DEFAULT_POLL_INTERVAL_S = 2.0
_DEFAULT_MAX_ITERATIONS = 10
_DEFAULT_MAX_TOTAL_WAIT_S = 20.0


def hierarchy_stability_fingerprint(snapshot: HierarchySnapshot) -> str:
    """
    Deterministic string fingerprint: node count plus per-node resource id, class, text.

    Row order matches ``snapshot.nodes`` (CSV parse order). Intended only to detect
    meaningful hierarchy churn (splash → home), not semantic equality.
    """
    parts: list[str] = [str(len(snapshot.nodes))]
    for node in snapshot.nodes:
        rid = (node.resource_id or "").strip()
        cls = (node.class_name or "").strip()
        txt = effective_visible_text(node)
        parts.append(f"{rid}\x1f{cls}\x1f{txt}")
    return "\x1e".join(parts)


@dataclass(frozen=True)
class HierarchyStableWaitOutcome:
    """Result of :func:`wait_for_hierarchy_stable`."""

    screen_stable: bool
    iterations_run: int
    final_node_count: int
    reason: str


def wait_for_hierarchy_stable(
    screen_service: MaestroScreenService,
    device_id: str,
    app_id: str,
    platform: Platform,
    *,
    initial_delay_s: float = 0.0,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    max_total_wait_s: float = _DEFAULT_MAX_TOTAL_WAIT_S,
    include_screenshot: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> HierarchyStableWaitOutcome:
    """
    After ``launch_app``, poll the hierarchy until it stops changing.

    Captures an initial snapshot, then up to ``max_iterations`` times: sleep
    ``poll_interval_s`` (subject to ``max_total_wait_s``), capture again, compare
    fingerprints. Exits when two consecutive captures match or a safety limit hits.
    """
    start = monotonic_fn()

    def _elapsed() -> float:
        return monotonic_fn() - start

    if initial_delay_s > 0.0:
        room = max_total_wait_s - _elapsed()
        delay = min(initial_delay_s, max(0.0, room))
        if delay > 0.0:
            log.info("hierarchy_wait_initial_delay", seconds=delay)
            sleep_fn(delay)

    obs0 = screen_service.observe_current_screen(
        app_id=app_id,
        platform=platform,
        device_id=device_id,
        include_screenshot=include_screenshot,
    )
    last_fp = hierarchy_stability_fingerprint(obs0.hierarchy)
    last_nodes = len(obs0.hierarchy.nodes)
    unchanged_streak = 0

    for iteration in range(1, max_iterations + 1):
        if _elapsed() >= max_total_wait_s:
            line = "SCREEN_STABLE false reason=max_total_wait"
            log.info(
                "hierarchy_stable_wait",
                line=line,
                elapsed_s=_elapsed(),
                iterations=iteration - 1,
            )
            return HierarchyStableWaitOutcome(
                screen_stable=False,
                iterations_run=iteration - 1,
                final_node_count=last_nodes,
                reason="max_total_wait",
            )

        room = max_total_wait_s - _elapsed()
        if room <= 0.0:
            line = "SCREEN_STABLE false reason=max_total_wait"
            log.info(
                "hierarchy_stable_wait",
                line=line,
                elapsed_s=_elapsed(),
                iterations=iteration - 1,
            )
            return HierarchyStableWaitOutcome(
                screen_stable=False,
                iterations_run=iteration - 1,
                final_node_count=last_nodes,
                reason="max_total_wait",
            )
        sleep_fn(min(poll_interval_s, room))

        obs = screen_service.observe_current_screen(
            app_id=app_id,
            platform=platform,
            device_id=device_id,
            include_screenshot=include_screenshot,
        )
        fp = hierarchy_stability_fingerprint(obs.hierarchy)
        n_nodes = len(obs.hierarchy.nodes)
        changed = fp != last_fp
        wait_line = f"WAIT iteration={iteration} changed={str(changed).lower()} nodes={n_nodes}"
        log.info(
            "hierarchy_wait_iteration",
            msg=wait_line,
            iteration=iteration,
            changed=changed,
            nodes=n_nodes,
        )

        if changed:
            last_fp = fp
            last_nodes = n_nodes
            unchanged_streak = 0
        else:
            unchanged_streak += 1
            if unchanged_streak >= 2:
                log.info("hierarchy_stable_wait", line="SCREEN_STABLE", iterations=iteration)
                return HierarchyStableWaitOutcome(
                    screen_stable=True,
                    iterations_run=iteration,
                    final_node_count=last_nodes,
                    reason="stable_twice",
                )

    line = "SCREEN_STABLE false reason=max_iterations"
    log.info("hierarchy_stable_wait", line=line, iterations=max_iterations)
    return HierarchyStableWaitOutcome(
        screen_stable=False,
        iterations_run=max_iterations,
        final_node_count=last_nodes,
        reason="max_iterations",
    )
