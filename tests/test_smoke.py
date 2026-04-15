"""Smoke tests for package import and shared infrastructure."""

from maestro_ai_agent import __version__
from maestro_ai_agent.app.settings import Settings
from maestro_ai_agent.shared.logging import configure_logging, get_logger


def test_package_version_is_set() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.log_level == "INFO"
    assert settings.log_json is False


def test_configure_logging_runs() -> None:
    configure_logging(level="INFO", json_format=False)
    log = get_logger("tests.smoke")
    log.info("smoke", ok=True)
