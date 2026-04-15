"""Machine-first JSON artifact for runtime exploration runs (``exploration_report.json``)."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.domain.flow import FlowDraft
from maestro_ai_agent.domain.hierarchy import HierarchySnapshot
from maestro_ai_agent.orchestrator.models import (
    PlanningOrchestrationResult,
    RunReport,
    ScenarioRunRequest,
    StepRunState,
)
from maestro_ai_agent.orchestrator.validation.hierarchy_compare import visible_text_tokens
from maestro_ai_agent.services.maestro.blocking_popup_dismissal import KnownBlockingPopupOutcome

EXPLORATION_REPORT_FILENAME = "exploration_report.json"
SCHEMA_VERSION = "1"


def hierarchy_digest(h: HierarchySnapshot, *, max_texts: int = 15) -> dict[str, Any]:
    """Small JSON-serializable hierarchy summary for exploration reports."""
    texts = sorted(visible_text_tokens(h))[:max_texts]
    return {
        "node_count": len(h.nodes),
        "parse_warnings": list(h.parse_warnings),
        "visible_text_sample": texts,
        "raw_csv_chars": len(h.raw_csv or ""),
    }


def serialize_known_blocking_popup_outcome(
    outcome: KnownBlockingPopupOutcome | None,
) -> dict[str, Any] | None:
    if outcome is None:
        return None
    data = asdict(outcome)
    data["blocker_episode"] = outcome.blocker_episode_dict()
    return data


def _popup_outcome_for_report(
    *,
    explicit: KnownBlockingPopupOutcome | None,
    launch_info: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if explicit is not None:
        return serialize_known_blocking_popup_outcome(explicit)
    if launch_info:
        nested = launch_info.get("blocking_popup")
        if isinstance(nested, dict):
            return nested
    return None


def _run_report_without_decision_log(report: RunReport) -> dict[str, Any]:
    data = report.model_dump(mode="json")
    data.pop("decision_log", None)
    return data


def _hierarchy_paths_for_step(step_index: int, st: StepRunState) -> tuple[str | None, str | None]:
    """Paths under ``steps/NN/`` (scenario runs always emit per-step hierarchy files)."""
    pre: str | None = None
    if st.observation and (st.observation.hierarchy.raw_csv or "").strip():
        pre = f"steps/{step_index:02d}/pre_hierarchy.csv"
    post: str | None = None
    po = st.post_action_observation
    if po and (po.hierarchy.raw_csv or "").strip():
        post = f"steps/{step_index:02d}/post_hierarchy.csv"
    return pre, post


def _flow_draft_step_for_scenario_index(
    flow: FlowDraft,
    scenario_step_index: int,
) -> dict[str, Any] | None:
    key = str(scenario_step_index)
    for fs in flow.steps:
        if fs.metadata.get("scenario_step_index") == key:
            return fs.model_dump(mode="json")
    return None


def _serialize_ranked_candidate(
    entry: object,
    *,
    show_regions: bool,
) -> dict[str, Any]:
    data = entry.model_dump(mode="json")
    if not show_regions:
        data["region_hint"] = None
        data["bounds"] = None
    return data


def _build_steps_payload(result: PlanningOrchestrationResult) -> list[dict[str, Any]]:
    steps_out: list[dict[str, Any]] = []
    tap_cfg = result.state.request.tap_resolution
    for i, st in enumerate(result.state.step_states):
        pre_path, post_path = _hierarchy_paths_for_step(i, st)
        obs_block: dict[str, Any] = {
            "pre_hierarchy_path": pre_path,
            "post_hierarchy_path": post_path,
        }
        if st.observation:
            obs_block["pre_hierarchy_digest"] = hierarchy_digest(st.observation.hierarchy)
        if st.post_action_observation:
            post_h = st.post_action_observation.hierarchy
            obs_block["post_hierarchy_digest"] = hierarchy_digest(post_h)

        ranked: list[dict[str, Any]] = []
        if st.ranking:
            lim = tap_cfg.max_target_suggestions
            ranked = [
                _serialize_ranked_candidate(c, show_regions=tap_cfg.show_target_regions)
                for c in st.ranking.ordered[:lim]
            ]

        chosen = st.planned_attempt.model_dump(mode="json") if st.planned_attempt else None
        chosen_cand = None
        if st.ranking and st.ranking.primary is not None:
            chosen_cand = _serialize_ranked_candidate(
                st.ranking.primary,
                show_regions=tap_cfg.show_target_regions,
            )

        if st.planned_attempt:
            action_type = st.planned_attempt.action.value
        else:
            action_type = st.intent.primary_action.value
        execution_block: dict[str, Any] | None = None
        if st.execution_outcome is not None:
            execution_block = {
                "action_type": action_type,
                "provider_execution": st.execution_outcome.model_dump(mode="json"),
            }

        validation_block: dict[str, Any] | None = None
        if st.post_action_validation is not None:
            validation_block = {
                "outcome": st.post_action_validation.outcome.value,
                "record": st.post_action_validation.model_dump(mode="json"),
            }

        flow_step = _flow_draft_step_for_scenario_index(
            result.state.flow_draft,
            st.scenario_step_index,
        )

        row: dict[str, Any] = {
            "index": i,
            "scenario_step_index": st.scenario_step_index,
            "raw_step_text": st.raw_step_text,
            "phase": st.phase.value,
            "validation_status": st.validation_status.value,
            "intent": st.intent.model_dump(mode="json"),
            "observation": obs_block,
            "selector_resolution": {
                "resolution_status": st.ranking.resolution_status if st.ranking else None,
                "ambiguity_reason": st.ranking.ambiguity_reason if st.ranking else None,
                "chosen": chosen,
                "chosen_candidate": chosen_cand,
                "ranked_candidates": ranked,
            },
            "execution": execution_block,
            "validation": validation_block,
            "flow_draft_step": flow_step,
            "warnings": list(st.warnings),
        }
        if st.blocker_episode is not None:
            row["blocker_episode"] = st.blocker_episode
        steps_out.append(row)
    return steps_out


def build_exploration_report_payload(
    *,
    run_type: str = "scenario_run",
    app_id: str,
    platform: Platform,
    device_id: str,
    raw_step: str | None,
    raw_scenario: str | None,
    canonical_scenario_used: bool,
    result: PlanningOrchestrationResult | None,
    orchestrator_ran: bool,
    launch_info: dict[str, Any] | None,
    popup_outcome: KnownBlockingPopupOutcome | None,
    preflight_launch_attempted: bool,
    preflight_launch_ok: bool | None,
    preflight_launch_message: str | None,
    maestro_draft_preview_relative_path: str | None,
    maestro_draft_preview_written: bool,
    canonical_scenario_path: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Assemble a versioned JSON document from orchestrator state (no AI, no prose generation).

    Hierarchy CSV bodies are **not** inlined; paths point to sidecar files under the output dir.
    """
    decision_log: list[dict[str, Any]] = []
    run_report_slice: dict[str, Any] | None = None
    flow_draft: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = []

    if result is not None:
        decision_log = [e.model_dump(mode="json") for e in result.report.decision_log]
        run_report_slice = _run_report_without_decision_log(result.report)
        flow_draft = result.state.flow_draft.model_dump(mode="json")
        steps = _build_steps_payload(result)

    popup_merged = _popup_outcome_for_report(explicit=popup_outcome, launch_info=launch_info)

    hierarchy_wait = None
    hierarchy_timing = None
    if launch_info:
        hierarchy_wait = launch_info.get("hierarchy_stable_wait")
        hierarchy_timing = launch_info.get("hierarchy_capture_timing")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_type": run_type,
        "app_id": app_id,
        "platform": platform.value if isinstance(platform, Platform) else str(platform),
        "device_id": device_id,
        "orchestrator_ran": orchestrator_ran,
        "input": {
            "raw_step": raw_step,
            "raw_scenario": raw_scenario,
            "canonical_scenario_used": canonical_scenario_used,
            "canonical_scenario_path": canonical_scenario_path,
        },
        "preflight": {
            "launch_attempted": preflight_launch_attempted,
            "launch_ok": preflight_launch_ok,
            "launch_message": preflight_launch_message,
            "hierarchy_capture_timing": hierarchy_timing,
            "hierarchy_stable_wait": hierarchy_wait,
            "popup_outcome": popup_merged,
        },
        "steps": steps,
        "decision_log": decision_log,
        "run_report": run_report_slice,
        "flow_draft": flow_draft,
        "maestro_draft_preview": {
            "yaml_path": maestro_draft_preview_relative_path,
            "written": maestro_draft_preview_written,
        },
    }

    rid = run_id
    if rid is None and result is not None:
        rid = str(result.state.context.run_id)
    if rid is not None:
        payload["run_id"] = rid

    return payload


def write_exploration_report(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Write ``exploration_report.json`` under ``output_dir`` (UTF-8)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / EXPLORATION_REPORT_FILENAME
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def platform_from_scenario_run_request(request: ScenarioRunRequest) -> Platform:
    """Resolve ``Platform`` from ``ScenarioRunRequest`` (scenario_input or parsed_scenario)."""
    if request.scenario_input is not None:
        return request.scenario_input.platform
    return request.parsed_scenario.input.platform
