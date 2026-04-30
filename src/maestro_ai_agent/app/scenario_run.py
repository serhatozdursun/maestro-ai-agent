"""Scenario-driven device run: preflight, canonical scenario, observe/plan/execute, artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import maestro_ai_agent as _maestro_pkg
from maestro_ai_agent.app.exploration_report import (
    build_exploration_report_payload,
    platform_from_scenario_run_request,
    write_exploration_report,
)
from maestro_ai_agent.app.maestro_draft_preview import (
    build_blocking_popup_optional_tap_yaml_lines,
    build_tap_on_yaml_lines,
    yaml_quote_scalar,
)
from maestro_ai_agent.domain.enums import ActionType, Platform, SelectorType
from maestro_ai_agent.domain.scenario import ScenarioInput
from maestro_ai_agent.domain.selectors.tap_resolution import (
    AmbiguityStrategy,
    TapResolutionSettings,
)
from maestro_ai_agent.orchestrator.enums import (
    DecisionExecutionFootprint,
    PlanningRunMode,
    RunStepPhase,
)
from maestro_ai_agent.orchestrator.models import (
    PlanningOrchestrationResult,
    RunDecisionLogEntry,
    ScenarioRunRequest,
)
from maestro_ai_agent.orchestrator.planning_service import ScenarioPlanningOrchestrator
from maestro_ai_agent.orchestrator.waiters.hierarchy_waiter import (
    HierarchyStableWaitOutcome,
    wait_for_hierarchy_stable,
)
from maestro_ai_agent.scenario.scenario_normalizer import (
    NormalizationResult,
    normalize_scenario_text,
)
from maestro_ai_agent.services.maestro.blocking_popup_dismissal import (
    KnownBlockingPopupOutcome,
    dismiss_known_blocking_popups_if_present,
)
from maestro_ai_agent.services.maestro.mcp_adapter import McpMaestroAdapter
from maestro_ai_agent.services.maestro.mcp_stdio_transport import McpStdioTransport
from maestro_ai_agent.services.maestro.models import ActionResult
from maestro_ai_agent.services.maestro.screen_service import MaestroScreenService
from maestro_ai_agent.shared.logging import get_logger

log = get_logger(__name__)

MAESTRO_DRAFT_PREVIEW_FILENAME = "maestro_draft_preview.yaml"
_PREFLIGHT_STABILITY_POLL_INTERVAL_S = 0.6
_PREFLIGHT_STABILITY_MAX_ITERATIONS = 3
_PREFLIGHT_STABILITY_MAX_TOTAL_WAIT_S = 1.8
_REQUIRED_MAESTRO_MCP_TOOLS = frozenset(
    {
        "list_devices",
        "launch_app",
        "inspect_view_hierarchy",
        "take_screenshot",
        "tap_on",
        "input_text",
        "run_flow",
    },
)
_MODERN_MINIMUM_MAESTRO_MCP_TOOLS = frozenset(
    {
        "list_devices",
        "run",
        "inspect_screen",
    },
)


def _launch_message_from_info(launch_info: dict[str, object] | None) -> str | None:
    if not launch_info:
        return None
    msg = launch_info.get("message")
    return str(msg) if msg else None


class ScenarioRunLaunchError(RuntimeError):
    """Raised when device preflight ``launch_app`` fails (no hierarchy is read)."""


class ScenarioRunBlockingPopupError(RuntimeError):
    """Raised when a blocking in-app dialog could not be dismissed; scenario is skipped."""


def _popup_dismiss_yaml_lines(popup: KnownBlockingPopupOutcome | None) -> list[str]:
    if popup is None:
        return []
    return build_blocking_popup_optional_tap_yaml_lines(
        handled=popup.handled,
        tap_selector_basis=popup.tap_selector_basis,
        dismiss_tap_text=popup.dismiss_tap_text,
        dismiss_tap_id=popup.dismiss_tap_id,
    )


_PREFLIGHT_LAUNCH_PERMISSIONS = {"all": "allow"}


def perform_device_preflight_launch(
    screen: MaestroScreenService,
    *,
    app_id: str,
    device_id: str,
) -> ActionResult:
    """Launch the target app before hierarchy reads (CLI scenario preflight)."""
    log.info(
        "device_preflight_launch_requested",
        app_id=app_id,
        device_id=device_id,
        launch_permissions=_PREFLIGHT_LAUNCH_PERMISSIONS,
    )
    result = screen.launch_app(
        app_id=app_id,
        device_id=device_id,
        permissions=_PREFLIGHT_LAUNCH_PERMISSIONS,
    )
    log.info(
        "device_preflight_launch_result",
        ok=result.ok,
        message=result.message,
    )
    return result


def run_device_preflight(
    *,
    screen: MaestroScreenService,
    app_id: str,
    platform: Platform,
    device_stripped: str,
    output_dir: Path,
    post_launch_settle_s: float,
    include_screenshot: bool,
) -> tuple[ActionResult, HierarchyStableWaitOutcome, KnownBlockingPopupOutcome]:
    """
    ``launch_app``, hierarchy stability wait, optional runtime blocker dismissal.

    Raises :class:`ScenarioRunLaunchError` or :class:`ScenarioRunBlockingPopupError` and
    writes failure artifacts when appropriate.
    """
    launch = perform_device_preflight_launch(
        screen,
        app_id=app_id,
        device_id=device_stripped,
    )
    if not launch.ok:
        _write_launch_failure_artifacts(
            output_dir=output_dir,
            app_id=app_id,
            platform=platform,
            device_id=device_stripped,
            launch=launch,
            initial_delay_before_stability_s=post_launch_settle_s,
        )
        _print_launch_failure(launch)
        msg = launch.message.strip() if launch.message else "launch_app failed"
        raise ScenarioRunLaunchError(msg)

    wait_outcome = wait_for_hierarchy_stable(
        screen,
        device_stripped,
        app_id,
        platform,
        initial_delay_s=post_launch_settle_s,
        poll_interval_s=_PREFLIGHT_STABILITY_POLL_INTERVAL_S,
        max_iterations=_PREFLIGHT_STABILITY_MAX_ITERATIONS,
        max_total_wait_s=_PREFLIGHT_STABILITY_MAX_TOTAL_WAIT_S,
        include_screenshot=include_screenshot,
    )
    log.info(
        "device_preflight_hierarchy_wait_summary",
        screen_stable=wait_outcome.screen_stable,
        iterations_run=wait_outcome.iterations_run,
        reason=wait_outcome.reason,
        final_node_count=wait_outcome.final_node_count,
    )

    popup_outcome = dismiss_known_blocking_popups_if_present(
        screen,
        device_id=device_stripped,
        app_id=app_id,
        platform=platform,
        include_screenshot=include_screenshot,
    )
    if popup_outcome.should_abort_run:
        _write_blocking_popup_failure_artifacts(
            output_dir=output_dir,
            app_id=app_id,
            platform=platform,
            device_id=device_stripped,
            popup_outcome=popup_outcome,
            initial_delay_before_stability_s=post_launch_settle_s,
            wait_outcome=wait_outcome,
        )
        log.info("popup_blocking_failure", reason=popup_outcome.reason)
        _print_blocking_popup_failure(popup_outcome)
        raise ScenarioRunBlockingPopupError(popup_outcome.reason)

    if popup_outcome.handled:
        wait_outcome = wait_for_hierarchy_stable(
            screen,
            device_stripped,
            app_id,
            platform,
            initial_delay_s=0.0,
            poll_interval_s=_PREFLIGHT_STABILITY_POLL_INTERVAL_S,
            max_iterations=_PREFLIGHT_STABILITY_MAX_ITERATIONS,
            max_total_wait_s=_PREFLIGHT_STABILITY_MAX_TOTAL_WAIT_S,
            include_screenshot=include_screenshot,
        )
        log.info(
            "device_preflight_hierarchy_wait_after_popup",
            screen_stable=wait_outcome.screen_stable,
            iterations_run=wait_outcome.iterations_run,
            reason=wait_outcome.reason,
            popup_pattern=popup_outcome.pattern_id,
        )

    return launch, wait_outcome, popup_outcome


def _merge_device_preflight_into_report(
    result: PlanningOrchestrationResult,
    *,
    app_id: str,
    device_id: str,
    initial_delay_before_stability_s: float,
    wait_outcome: HierarchyStableWaitOutcome,
) -> PlanningOrchestrationResult:
    """Prepend a decision row so audit readers see hierarchy is post-launch."""
    stable_s = "stable" if wait_outcome.screen_stable else "not_stable"
    preflight = RunDecisionLogEntry(
        scenario_step_index=-1,
        raw_step_text="[device preflight] launch_app",
        intent_goal_summary="Foreground target app before scenario steps (CLI preflight).",
        intent_primary_action=ActionType.LAUNCH_APP,
        execution_footprint=DecisionExecutionFootprint.DEVICE_PREFLIGHT_LAUNCH_SUCCEEDED,
        step_phase=RunStepPhase.PENDING,
        provider_action="launch_app",
        provider_ok=True,
        provider_message=None,
        limitations=[
            "Subsequent rows use hierarchy captured **after** launch_app, an optional "
            f"initial delay ({initial_delay_before_stability_s}s), and a hierarchy stability "
            f"wait (outcome={stable_s}, reason={wait_outcome.reason!r}, "
            f"wait_iterations={wait_outcome.iterations_run}).",
        ],
    )
    new_log = [preflight, *result.report.decision_log]
    lim0 = (
        f"Device preflight: launch_app(app_id={app_id!r}, device_id={device_id!r}) succeeded; "
        f"initial_delay_before_stability_s={initial_delay_before_stability_s}; "
        f"hierarchy_stable_wait={wait_outcome.reason!r} "
        f"(screen_stable={wait_outcome.screen_stable}, "
        f"iterations={wait_outcome.iterations_run}). **First orchestrator observe is a "
        "separate hierarchy read after preflight.**"
    )
    new_report = result.report.model_copy(
        update={
            "decision_log": new_log,
            "limitations": [lim0, *result.report.limitations],
            "total_intents": len(new_log),
        },
    )
    return result.model_copy(update={"report": new_report})


def _write_placeholder_maestro_preview(output_dir: Path, comment: str) -> None:
    (output_dir / MAESTRO_DRAFT_PREVIEW_FILENAME).write_text(
        f"# {comment}\n",
        encoding="utf-8",
    )


def _write_launch_failure_artifacts(
    *,
    output_dir: Path,
    app_id: str,
    platform: Platform,
    device_id: str,
    launch: ActionResult,
    initial_delay_before_stability_s: float,
) -> None:
    run_id = str(uuid4())
    _write_placeholder_maestro_preview(
        output_dir,
        "scenario-run: launch_app failed; no Maestro draft preview generated.",
    )
    write_exploration_report(
        output_dir,
        build_exploration_report_payload(
            run_type="scenario_run",
            app_id=app_id,
            platform=platform,
            device_id=device_id,
            raw_step=None,
            raw_scenario=None,
            canonical_scenario_used=False,
            result=None,
            orchestrator_ran=False,
            launch_info=None,
            popup_outcome=None,
            preflight_launch_attempted=True,
            preflight_launch_ok=False,
            preflight_launch_message=launch.message,
            maestro_draft_preview_relative_path=MAESTRO_DRAFT_PREVIEW_FILENAME,
            maestro_draft_preview_written=False,
            run_id=run_id,
        ),
    )


def _write_blocking_popup_failure_artifacts(
    *,
    output_dir: Path,
    app_id: str,
    platform: Platform,
    device_id: str,
    popup_outcome: KnownBlockingPopupOutcome,
    initial_delay_before_stability_s: float,
    wait_outcome: HierarchyStableWaitOutcome | None,
) -> None:
    run_id = str(uuid4())
    _write_placeholder_maestro_preview(
        output_dir,
        "scenario-run: blocking dialog could not be dismissed; scenario not executed.",
    )
    launch_info_er: dict[str, object] = {
        "hierarchy_capture_timing": "after_launch_and_hierarchy_stable_wait",
        "initial_delay_before_stability_s": initial_delay_before_stability_s,
    }
    if wait_outcome is not None:
        launch_info_er["hierarchy_stable_wait"] = {
            "screen_stable": wait_outcome.screen_stable,
            "iterations_run": wait_outcome.iterations_run,
            "final_node_count": wait_outcome.final_node_count,
            "reason": wait_outcome.reason,
        }
    write_exploration_report(
        output_dir,
        build_exploration_report_payload(
            run_type="scenario_run",
            app_id=app_id,
            platform=platform,
            device_id=device_id,
            raw_step=None,
            raw_scenario=None,
            canonical_scenario_used=False,
            result=None,
            orchestrator_ran=False,
            launch_info=launch_info_er,
            popup_outcome=popup_outcome,
            preflight_launch_attempted=True,
            preflight_launch_ok=True,
            preflight_launch_message=None,
            maestro_draft_preview_relative_path=MAESTRO_DRAFT_PREVIEW_FILENAME,
            maestro_draft_preview_written=False,
            run_id=run_id,
        ),
    )


def _print_blocking_popup_failure(popup: KnownBlockingPopupOutcome) -> None:
    print("", file=sys.stdout)
    print("=== scenario-run: blocking dialog not dismissed ===", file=sys.stdout)
    print(f"pattern={popup.pattern_id!r} reason={popup.reason!r}", file=sys.stdout)
    if popup.popup_tool_name and popup.popup_tool_args is not None:
        print(
            f"last_tool={popup.popup_tool_name!r} args={popup.popup_tool_args!r}",
            file=sys.stdout,
        )
    print("Scenario was not started.", file=sys.stdout)
    print("", file=sys.stdout)


def _print_launch_failure(launch: ActionResult) -> None:
    print("", file=sys.stdout)
    print("=== scenario-run: launch_app failed ===", file=sys.stdout)
    print(f"ok=False message={launch.message!r}", file=sys.stdout)
    print("No inspect_view_hierarchy call was made.", file=sys.stdout)
    print("", file=sys.stdout)


def _selector_type_for_flow_hint(expression: str | None) -> SelectorType:
    e = (expression or "").strip().lower()
    if e.startswith("id:"):
        return SelectorType.ID
    if e.startswith("point:"):
        return SelectorType.POINT
    if e.startswith("text:"):
        return SelectorType.TEXT
    return SelectorType.TEXT


def build_maestro_draft_preview_yaml(
    *,
    app_id: str,
    result: PlanningOrchestrationResult,
    popup_dismiss_yaml_lines: list[str] | None = None,
) -> str:
    """Best-effort Maestro YAML from the accumulated flow draft (tap + inputText only)."""
    lines = [
        "# maestro_draft_preview: flow draft → Maestro YAML (review before use in a real project)",
        f"appId: {app_id}",
        "---",
    ]
    if popup_dismiss_yaml_lines:
        lines.extend(popup_dismiss_yaml_lines)
    for fs in result.state.flow_draft.steps:
        if fs.action is ActionType.TAP and fs.target_selector_hint:
            lines.extend(
                build_tap_on_yaml_lines(
                    _selector_type_for_flow_hint(fs.target_selector_hint),
                    fs.target_selector_hint,
                ),
            )
        elif fs.action is ActionType.INPUT_TEXT and fs.input_value is not None:
            lines.append(f"- inputText: {yaml_quote_scalar(fs.input_value)}")
        elif fs.action is ActionType.DISMISS_BLOCKER:
            hint = (fs.target_selector_hint or "").strip()
            low = hint.lower()
            if low.startswith("id:"):
                rid = hint[3:].strip()
                lines.extend(
                    build_blocking_popup_optional_tap_yaml_lines(
                        handled=True,
                        tap_selector_basis="id",
                        dismiss_tap_text=None,
                        dismiss_tap_id=rid,
                    ),
                )
            elif low.startswith("text:"):
                t = hint[5:].strip()
                lines.extend(
                    build_blocking_popup_optional_tap_yaml_lines(
                        handled=True,
                        tap_selector_basis="text",
                        dismiss_tap_text=t,
                        dismiss_tap_id=None,
                    ),
                )
    return "\n".join(lines) + "\n"


def _write_scenario_run_artifacts(
    result: PlanningOrchestrationResult,
    *,
    output_dir: Path,
    app_id: str,
    launch_info: dict[str, object] | None,
    raw_scenario: str,
    normalization: NormalizationResult,
    popup_outcome: KnownBlockingPopupOutcome | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "canonical_scenario.json").write_text(
        json.dumps(normalization.canonical.model_dump(), indent=2, default=str),
        encoding="utf-8",
    )

    for i, st in enumerate(result.state.step_states):
        step_dir = output_dir / "steps" / f"{i:02d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        if st.observation and (st.observation.hierarchy.raw_csv or "").strip():
            (step_dir / "pre_hierarchy.csv").write_text(
                st.observation.hierarchy.raw_csv or "",
                encoding="utf-8",
            )
        post_obs = st.post_action_observation
        post_csv = (post_obs.hierarchy.raw_csv or "").strip() if post_obs else ""
        if post_obs and post_csv:
            (step_dir / "post_hierarchy.csv").write_text(
                post_obs.hierarchy.raw_csv or "",
                encoding="utf-8",
            )

    popup_yaml = _popup_dismiss_yaml_lines(popup_outcome)
    maestro_written = False
    try:
        (output_dir / MAESTRO_DRAFT_PREVIEW_FILENAME).write_text(
            build_maestro_draft_preview_yaml(
                app_id=app_id,
                result=result,
                popup_dismiss_yaml_lines=popup_yaml if popup_yaml else None,
            ),
            encoding="utf-8",
        )
        maestro_written = True
        if popup_yaml:
            log.info(
                "scenario_run_yaml_preflight_popup_dismiss",
                yaml_line_count=len(popup_yaml),
                tap_selector_basis=popup_outcome.tap_selector_basis if popup_outcome else None,
            )
    except (ValueError, TypeError):
        (output_dir / MAESTRO_DRAFT_PREVIEW_FILENAME).write_text(
            "# maestro_draft_preview: could not emit YAML from flow draft\n",
            encoding="utf-8",
        )

    req = result.state.request
    device_resolved = (req.device_id or result.state.context.device_id or "").strip()
    write_exploration_report(
        output_dir,
        build_exploration_report_payload(
            run_type="scenario_run",
            app_id=app_id,
            platform=platform_from_scenario_run_request(req),
            device_id=device_resolved,
            raw_step=None,
            raw_scenario=raw_scenario,
            canonical_scenario_used=True,
            result=result,
            orchestrator_ran=True,
            launch_info=launch_info,
            popup_outcome=popup_outcome,
            preflight_launch_attempted=True,
            preflight_launch_ok=bool(launch_info.get("ok")) if launch_info else None,
            preflight_launch_message=_launch_message_from_info(launch_info),
            maestro_draft_preview_relative_path=MAESTRO_DRAFT_PREVIEW_FILENAME,
            maestro_draft_preview_written=maestro_written,
            canonical_scenario_path="canonical_scenario.json",
        ),
    )


def _print_scenario_console_report(
    result: PlanningOrchestrationResult,
    *,
    launch_info: dict[str, object] | None,
) -> None:
    out = sys.stdout
    print("", file=out)
    print("=== scenario-run ===", file=out)
    if launch_info:
        print(f"preflight: launch_app ok={launch_info.get('ok')}", file=out)
    print(f"summary: {result.report.summary}", file=out)
    print(f"steps_run: {len(result.state.step_states)}", file=out)
    for st in result.state.step_states:
        print(
            f"  [{st.scenario_step_index}] {st.raw_step_text!r} → "
            f"phase={st.phase.value} validation={st.validation_status.value}",
            file=out,
        )
    print(
        f"Artifacts: exploration_report.json, canonical_scenario.json, steps/, "
        f"{MAESTRO_DRAFT_PREVIEW_FILENAME}",
        file=out,
    )
    print("", file=out)


def run_scenario_exploration(
    *,
    app_id: str,
    platform: Platform,
    scenario_text: str,
    device_id: str | None,
    output_dir: Path,
    mcp_command: str,
    include_screenshot: bool = False,
    mcp_protocol_version: str = "2024-11-05",
    post_launch_settle_s: float = 0.2,
    max_steps: int | None = None,
    tap_ambiguity_strategy: str = "auto",
    tap_max_target_suggestions: int = 8,
    tap_show_target_regions: bool = True,
    tap_prefer_target_kind: str = "auto",
) -> PlanningOrchestrationResult:
    """
    Canonical scenario normalization, then observe / plan / execute / validate per step.

    Writes ``exploration_report.json``, ``canonical_scenario.json``, per-step hierarchies
    under ``steps/NN/``, and ``maestro_draft_preview.yaml`` when the flow draft maps.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    device_stripped = (device_id or "").strip()
    if not device_stripped:
        msg = "scenario-run requires --device (Maestro deviceId / UDID)."
        raise ValueError(msg)

    stripped_scenario = scenario_text.strip()
    if not stripped_scenario:
        msg = "scenario text must contain at least one non-empty line."
        raise ValueError(msg)

    normalization = normalize_scenario_text(stripped_scenario, enable_ai_fallback=False)

    log.info(
        "scenario_run_start",
        app_id=app_id,
        platform=platform.value,
        device_id=device_stripped,
        output_dir=str(output_dir),
        mcp_command=mcp_command,
        post_launch_settle_s=post_launch_settle_s,
        max_steps=max_steps,
    )
    _tap_qualifier_signals = any(
        (s.action or "").strip().lower() == "tap"
        and (
            (s.target_qualifier_phrase_raw or "").strip() or (s.target_container_hint or "").strip()
        )
        for s in normalization.canonical.steps
    )
    log.info(
        "scenario_run_runtime_identity",
        maestro_ai_agent_package_path=getattr(_maestro_pkg, "__file__", None),
        maestro_ai_agent_version=getattr(_maestro_pkg, "__version__", None),
        use_canonical_scenario_normalization=True,
        parsed_steps_path=(
            "normalize_scenario_text → build_parsed_scenario_from_canonical "
            "(canonical_to_parsed_v1) → plan_intents"
        ),
        contextual_tap_qualifiers_in_scenario=_tap_qualifier_signals,
    )

    with McpStdioTransport.from_shell_command(
        mcp_command,
        protocol_version=mcp_protocol_version,
    ) as transport:
        advertised_tools = set(transport.list_tool_names())
        legacy_missing = sorted(_REQUIRED_MAESTRO_MCP_TOOLS - advertised_tools)
        modern_missing = sorted(_MODERN_MINIMUM_MAESTRO_MCP_TOOLS - advertised_tools)
        if legacy_missing and modern_missing:
            advertised_preview = ", ".join(sorted(advertised_tools)) or "<none>"
            missing_preview = ", ".join(legacy_missing)
            msg = (
                "Incompatible Maestro MCP server. This build expects legacy tools "
                f"({missing_preview} missing), or modern minimum tools "
                f"({', '.join(modern_missing)} missing). Your server advertises: "
                f"{advertised_preview}."
            )
            raise RuntimeError(msg)
        provider = McpMaestroAdapter(transport)
        screen = MaestroScreenService(provider)

        launch, wait_outcome, popup_outcome = run_device_preflight(
            screen=screen,
            app_id=app_id,
            platform=platform,
            device_stripped=device_stripped,
            output_dir=output_dir,
            post_launch_settle_s=post_launch_settle_s,
            include_screenshot=include_screenshot,
        )

        orch = ScenarioPlanningOrchestrator(screen)
        try:
            amb = AmbiguityStrategy(tap_ambiguity_strategy.strip().lower())
        except ValueError as e:
            msg = (
                f"Invalid tap_ambiguity_strategy {tap_ambiguity_strategy!r}; "
                "use auto, suggest, or fail."
            )
            raise ValueError(msg) from e
        tap_resolution = TapResolutionSettings(
            ambiguity_strategy=amb,
            max_target_suggestions=tap_max_target_suggestions,
            show_target_regions=tap_show_target_regions,
            prefer_target_kind=tap_prefer_target_kind.strip().lower(),
        )
        request = ScenarioRunRequest(
            scenario_input=ScenarioInput(
                scenario_text=stripped_scenario,
                app_id=app_id,
                platform=platform,
            ),
            device_id=device_stripped,
            include_screenshot=include_screenshot,
            planning_mode=PlanningRunMode.OBSERVE_PLAN_EXECUTE,
            use_canonical_scenario_normalization=True,
            stop_on_first_hard_failure=True,
            max_steps=max_steps,
            run_label="scenario-run",
            tap_resolution=tap_resolution,
        )
        result = orch.run_observe_plan_execute(request)
        result = _merge_device_preflight_into_report(
            result,
            app_id=app_id,
            device_id=device_stripped,
            initial_delay_before_stability_s=post_launch_settle_s,
            wait_outcome=wait_outcome,
        )

    launch_info = {
        "requested": True,
        "ok": True,
        "message": launch.message,
        "initial_delay_before_stability_s": post_launch_settle_s,
        "hierarchy_capture_timing": "after_launch_and_hierarchy_stable_wait",
        "hierarchy_stable_wait": {
            "screen_stable": wait_outcome.screen_stable,
            "iterations_run": wait_outcome.iterations_run,
            "final_node_count": wait_outcome.final_node_count,
            "reason": wait_outcome.reason,
        },
        "blocking_popup": {
            "handled": popup_outcome.handled,
            "should_abort_run": popup_outcome.should_abort_run,
            "pattern_id": popup_outcome.pattern_id,
            "reason": popup_outcome.reason,
            "popup_tool_name": popup_outcome.popup_tool_name,
            "popup_tool_args": popup_outcome.popup_tool_args,
            "tap_selector_basis": popup_outcome.tap_selector_basis,
            "blocker_episode": popup_outcome.blocker_episode_dict(),
        },
    }
    _write_scenario_run_artifacts(
        result,
        output_dir=output_dir,
        app_id=app_id,
        launch_info=launch_info,
        raw_scenario=stripped_scenario,
        normalization=normalization,
        popup_outcome=popup_outcome,
    )
    _print_scenario_console_report(result, launch_info=launch_info)
    log.info("scenario_run_done", summary=result.report.summary)
    return result
