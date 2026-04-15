"""Full normalization pipeline (no orchestrator)."""

from maestro_ai_agent.scenario.canonical_model import CanonicalScenario, CanonicalStep
from maestro_ai_agent.scenario.classifier import ScenarioInputProfile
from maestro_ai_agent.scenario.scenario_normalizer import normalize_scenario_text


class _StubAiParser:
    """Returns canonical steps only (no Maestro)."""

    def normalize_to_canonical(
        self,
        *,
        text: str,
        profile: ScenarioInputProfile,
        draft: CanonicalScenario,
        confidence_reason: str,
    ) -> CanonicalScenario | None:
        return CanonicalScenario(
            steps=[
                CanonicalStep(
                    action="tap",
                    target="Recovered",
                    value=None,
                    index=0,
                    source_text="ai-normalized",
                ),
            ],
            warnings=list(draft.warnings),
        )


class _ExplodingAiParser:
    def normalize_to_canonical(
        self,
        *,
        text: str,
        profile: ScenarioInputProfile,
        draft: CanonicalScenario,
        confidence_reason: str,
    ) -> CanonicalScenario | None:
        raise RuntimeError("network down")


def test_ai_fallback_not_invoked_when_disabled() -> None:
    out = normalize_scenario_text("mystery xyz", enable_ai_fallback=False)
    assert out.used_ai_fallback is False
    assert out.canonical.steps[0].action == "unknown"


def test_ai_fallback_invoked_when_low_confidence_and_backend_returns() -> None:
    out = normalize_scenario_text(
        "mystery xyz",
        enable_ai_fallback=True,
        ai_fallback=_StubAiParser(),
        confidence_threshold=0.99,
    )
    assert out.used_ai_fallback is True
    assert out.canonical.steps[0].action == "tap"
    assert out.canonical.steps[0].target == "Recovered"
    assert any("AI fallback adjusted" in w for w in out.warnings)


def test_ai_fallback_failure_adds_warning() -> None:
    out = normalize_scenario_text(
        "mystery xyz",
        enable_ai_fallback=True,
        ai_fallback=_ExplodingAiParser(),
        confidence_threshold=0.99,
    )
    assert out.used_ai_fallback is False
    assert any("AI fallback failed" in w for w in out.warnings)


def test_enable_ai_without_backend_skips_ai() -> None:
    out = normalize_scenario_text("mystery xyz", enable_ai_fallback=True, ai_fallback=None)
    assert out.used_ai_fallback is False
