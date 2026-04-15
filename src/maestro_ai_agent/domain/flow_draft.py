"""Helpers to accumulate validated steps into a :class:`FlowDraft` (no Maestro YAML)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from maestro_ai_agent.domain.flow import FlowDraft, FlowStep


class FlowDraftBuilder:
    """Append-only builder for successful :class:`FlowStep` entries."""

    def __init__(self, *, run_label: str | None = None) -> None:
        now = datetime.now(UTC)
        self._draft = FlowDraft(steps=[], run_label=run_label, created_at=now, updated_at=now)

    @property
    def step_count(self) -> int:
        return len(self._draft.steps)

    def append_successful(self, step: FlowStep) -> FlowStep:
        """
        Append a step that has already passed validation in the orchestrator.

        ``FlowStep.sequence`` must equal the current draft length (0-based).
        """
        return self._append_at_end(step)

    def append_planned(self, step: FlowStep) -> FlowStep:
        """
        Append a planning-stage step (not executed / not validated on device).

        Metadata is merged with ``lifecycle=planned``, ``executed=false``, ``validated=false``.
        """
        merged_meta = {
            **step.metadata,
            "lifecycle": "planned",
            "executed": "false",
            "validated": "false",
        }
        planned = step.model_copy(update={"metadata": merged_meta})
        return self._append_at_end(planned)

    def append_executed_unvalidated(self, step: FlowStep) -> FlowStep:
        """
        Append after a successful provider ``tap_on`` / ``input_text`` call.

        ``ActionResult.ok`` from Maestro does **not** mean validation goals passed—only
        that the tool invocation completed. Metadata records ``validated=false`` and
        ``validation=deferred`` until a future validator runs.
        """
        merged_meta = {
            **step.metadata,
            "lifecycle": "executed_unvalidated",
            "executed": "true",
            "validated": "false",
            "validation": "deferred",
        }
        executed = step.model_copy(update={"metadata": merged_meta})
        return self._append_at_end(executed)

    def append_executed_validated(self, step: FlowStep) -> FlowStep:
        """Append after provider success and conservative hierarchy validation passed."""
        merged_meta = {
            **step.metadata,
            "lifecycle": "executed_validated",
            "executed": "true",
            "validated": "true",
            "validation_outcome": "validated",
        }
        return self._append_at_end(step.model_copy(update={"metadata": merged_meta}))

    def append_executed_validation_failed(self, step: FlowStep) -> FlowStep:
        """Append when provider succeeded but post-action validation contradicted goals."""
        merged_meta = {
            **step.metadata,
            "lifecycle": "executed_validation_failed",
            "executed": "true",
            "validated": "false",
            "validation_outcome": "validation_failed",
        }
        return self._append_at_end(step.model_copy(update={"metadata": merged_meta}))

    def append_executed_validation_inconclusive(self, step: FlowStep) -> FlowStep:
        """Append when provider succeeded but evidence was too weak to pass or fail."""
        merged_meta = {
            **step.metadata,
            "lifecycle": "executed_validation_inconclusive",
            "executed": "true",
            "validated": "false",
            "validation_outcome": "validation_inconclusive",
        }
        return self._append_at_end(step.model_copy(update={"metadata": merged_meta}))

    def append_executed_validation_skipped(self, step: FlowStep) -> FlowStep:
        """Append when post-action hierarchy could not be validated safely (e.g. empty)."""
        merged_meta = {
            **step.metadata,
            "lifecycle": "executed_validation_skipped",
            "executed": "true",
            "validated": "false",
            "validation_outcome": "validation_skipped",
        }
        return self._append_at_end(step.model_copy(update={"metadata": merged_meta}))

    def _append_at_end(self, step: FlowStep) -> FlowStep:
        expected = len(self._draft.steps)
        if step.sequence != expected:
            msg = f"FlowStep.sequence must be {expected}, got {step.sequence}"
            raise ValueError(msg)
        updated = self._draft.model_copy(
            update={
                "steps": [*self._draft.steps, step],
                "updated_at": datetime.now(UTC),
            },
            deep=True,
        )
        self._draft = updated
        return step

    def draft(self) -> FlowDraft:
        """Return a deep copy of the current draft (safe to mutate externally)."""
        return self._draft.model_copy(deep=True)

    def to_serializable(self) -> dict[str, Any]:
        """Serialize the draft to JSON-friendly primitives (UUIDs/datetimes as strings)."""
        return self.draft().model_dump(mode="json")
