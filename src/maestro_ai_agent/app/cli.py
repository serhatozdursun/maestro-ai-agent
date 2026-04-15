"""Command-line interface (Typer)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from maestro_ai_agent import __version__
from maestro_ai_agent.app.scenario_run import (
    ScenarioRunBlockingPopupError,
    ScenarioRunLaunchError,
    run_scenario_exploration,
)
from maestro_ai_agent.domain.enums import Platform
from maestro_ai_agent.scenario.scenario_cli_text import (
    ScenarioInputSourceError,
    resolve_scenario_text_for_cli,
)
from maestro_ai_agent.services.maestro.hierarchy_csv import HierarchyParseError
from maestro_ai_agent.services.maestro.transport_types import MaestroIntegrationError
from maestro_ai_agent.shared.logging import configure_logging

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Scenario-driven mobile exploration with Maestro (runtime artifacts + draft preview).\n\n"
        "Scenario steps support Scroll (Up/Down/Left/Right) and Swipe: use Swipe left (or "
        "right/up/down) for a full-screen directional gesture (same Maestro swipe template as "
        "Scroll), or targeted lines Swipe left on 'UI text' and Swipe 'UI text' left. "
        "Full list: maestro-ai-agent scenario-run --help; see docs/ai-scenario-grammar.md."
    ),
)


def main() -> None:
    """Console script entrypoint for setuptools."""
    app()


@app.callback()
def _main_callback() -> None:
    """Root callback (reserved for global options in future iterations)."""
    return None


@app.command("version")
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command("scenario-run")
def scenario_run_cmd(
    app_id: str = typer.Option(..., "--app-id", help="Application id / bundle id (Maestro appId)."),
    platform: str = typer.Option(
        "android",
        "--platform",
        "-p",
        help="android or ios (must match the connected device).",
    ),
    scenario_file: Annotated[
        Path | None,
        typer.Option(
            "--scenario-file",
            "-f",
            help="Path to a text file with one scenario step per line (newline-separated).",
        ),
    ] = None,
    scenario: Annotated[
        str | None,
        typer.Option(
            "--scenario",
            "--scenario-text",
            "-S",
            help=(
                "Inline multi-line scenario text. Mutually exclusive with --scenario-file "
                "and --step."
            ),
        ),
    ] = None,
    step: Annotated[
        list[str],
        typer.Option(
            "--step",
            help=(
                "Single scenario step; repeat flag to preserve order "
                "(see docs/ai-scenario-grammar.md)."
            ),
        ),
    ] = [],  # noqa: B006
    device_id: str = typer.Option(
        ...,
        "--device",
        "-d",
        help="Device id (Maestro deviceId / UDID); required for preflight launch_app.",
    ),
    output_dir: str = typer.Option(
        "scenario-out",
        "--output-dir",
        "-o",
        help="Directory for exploration_report.json, canonical_scenario.json, steps/, "
        "maestro_draft_preview.yaml.",
    ),
    max_steps: Annotated[
        int | None,
        typer.Option("--max-steps", help="Optional cap on scenario steps (default: all lines)."),
    ] = None,
    mcp_command: str = typer.Option(
        "maestro mcp",
        "--mcp-command",
        help='Shell command to start the Maestro MCP server (default: "maestro mcp").',
    ),
    mcp_protocol_version: str = typer.Option(
        "2024-11-05",
        "--mcp-protocol-version",
        help="MCP protocolVersion sent in initialize (try 2025-03-26 if initialize fails).",
    ),
    screenshot: bool = typer.Option(
        False,
        "--screenshot/--no-screenshot",
        help="Request screenshot during observe (secondary to hierarchy).",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="Python log level for scenario-run logs.",
    ),
    log_json: bool = typer.Option(False, "--log-json", help="Emit structured logs as JSON lines."),
    post_launch_settle: float = typer.Option(
        0.2,
        "--post-launch-settle",
        help="Seconds before first post-launch hierarchy sample (default 0.2s; then fast stability polling).",
        min=0.0,
        max=60.0,
    ),
    ambiguity_strategy: Annotated[
        str,
        typer.Option(
            "--ambiguity-strategy",
            help=(
                "Tap-only: when two hierarchy-backed targets score similarly, "
                "auto keeps the best ranked candidate; suggest/fail skip planning the tap "
                "and expose ranked_candidates in exploration_report.json."
            ),
        ),
    ] = "auto",
    max_target_suggestions: Annotated[
        int,
        typer.Option(
            "--max-target-suggestions",
            help="Cap ranked tap candidates written to exploration_report / decision log rows.",
            min=1,
            max=50,
        ),
    ] = 8,
    show_target_regions: Annotated[
        bool,
        typer.Option(
            "--show-target-regions/--no-show-target-regions",
            help=(
                "Include coarse bounds-derived region hints on ranked tap candidates "
                "in JSON output."
            ),
        ),
    ] = True,
    prefer_target_kind: Annotated[
        str,
        typer.Option(
            "--prefer-target-kind",
            help=(
                "Optional structural bias for taps: auto | tab | button | banner | menu_item "
                "(soft score tilt; hierarchy still gates proposals)."
            ),
        ),
    ] = "auto",
) -> None:
    """
    Run a scenario on a real device: canonical normalization, then observe / plan / execute /
    validate per line. Stops on the first hard failure.

    Command name is ``scenario-run`` (not ``run-scenario``). Flags are in the Options table
    below; the following is a compact guide for authoring scenario text (for humans and
    external AI tools).

    \b
    Scenario input (choose exactly one path; all normalize to the same internal scenario):

    \b
      1) Scenario file — one step per line:

         --scenario-file scenario.txt

    \b
      2) Inline multi-line text (also ``--scenario-text`` / ``-S``), e.g.:

         --scenario "
         Tap 'Search'
         Enter 'shoe'
         Press Enter
         "

    \b
      3) Repeated flags (order preserved):

         --step "Tap 'Search'" --step "Enter 'shoe'" --step "Press Enter"

    \b
    ---------------------------------------------------------------------
    AI SCENARIO GRAMMAR (short guide)
    ---------------------------------------------------------------------

    This grammar is designed for both humans and external AI tools.

    Typical workflow for an AI tool:

    1. Generate scenario steps using the grammar below.
    2. Run `maestro-ai-agent scenario-run`.
    3. Read the output artifacts (especially `exploration_report.json`).
    4. Optionally convert the generated preview YAML into project-specific Maestro flows.

    The authoritative machine-readable output is `exploration_report.json`.
    The `maestro_draft_preview.yaml` file is a convenience draft and may require adaptation.

    \b
    Examples:

      Tap 'Search'
      Tap 'Search for Products'
      Enter 'shoe'
      Press Enter
      AssertVisible 'Results'
      Scroll Down
      Swipe left
      Swipe left on 'Story card'

    \b
    Common UI region hints (recommended):

      Tap 'Shop' in the tab bar
      Tap 'Shop' in the header
      Tap 'Shop' in the footer
      Tap 'Close' in the popup

    After the quoted label, ``on`` / ``in`` / ``from`` plus a short region phrase nudges
    selector ranking toward elements in that part of the screen. These are soft hints for
    location, not strict filters—the ranker may still consider other nodes when hierarchy
    evidence warrants it.

    Typical phrase → UI surface (informal mapping):

      tab bar   → bottom navigation, UITabBar, BottomNavigationView
      header    → navigation bar, top toolbar
      footer    → bottom container
      popup     → modal, dialog, alert

    When multiple elements share the same visible label, adding a region hint greatly improves
    tap accuracy.

    \b
    Tap disambiguation (optional, deterministic):

      - After the quoted label you may add ``on`` / ``in`` / ``from`` plus a short UI region phrase
        (e.g. ``Tap 'Close' in the popup``). Synonyms map to soft ranking hints, not hard filters.
      - ``--ambiguity-strategy`` controls close-match taps: ``auto`` keeps the best ranked target;
        ``suggest`` / ``fail`` avoid committing a tap and return ranked candidates for review.
      - ``--prefer-target-kind`` adds a small structural bias (tab, button, banner, menu_item).

    \b
    Supported action shapes (typical lines):

      Tap 'Visible Text'
      Enter 'text'          (also Type / Input with quoted text)
      Press Enter
      AssertVisible 'Text'   (hierarchy check uses ranked id/text when available, else quoted text)
      AssertNotVisible 'Text' (same ranked-first rule when a primary selector exists)
      Scroll Down           (or Scroll Up / Left / Right; directional only—no per-element scroll grammar)
      Swipe Left            (or Swipe Right / Up / Down; same run_flow swipe as Scroll)
      Swipe left on 'Label' (or Swipe 'Label' left; swipe.from uses ranked id/text when available, else the quoted label as text)
      ScrollUntilVisible 'Text' (element uses ranked id/text when hierarchy provides a primary, else quoted text)
      Dismiss popup         (blocking UI; bounded runtime handling)

    \b
    Guidelines:

      - Prefer quoted visible text for taps and asserts.
      - One action per step line.
      - Keep steps simple and deterministic.
      - Do not paste raw Maestro YAML as scenario input.

    \b
    Example invocation:

      maestro-ai-agent scenario-run \\
        --app-id com.example.app \\
        --platform ios \\
        --device DEVICE_ID \\
        --step "Tap 'Search'" \\
        --step "Enter 'shoe'" \\
        --step "Press Enter"
    """
    configure_logging(level=log_level, json_format=log_json)
    try:
        raw = resolve_scenario_text_for_cli(
            scenario_file=scenario_file,
            scenario=scenario,
            steps=step,
        )
    except ScenarioInputSourceError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from e
    try:
        plat = Platform(platform.strip().lower())
    except ValueError as e:
        typer.echo(f"Invalid --platform {platform!r}: use android or ios.", err=True)
        raise typer.Exit(code=2) from e
    try:
        run_scenario_exploration(
            app_id=app_id,
            platform=plat,
            scenario_text=raw,
            device_id=device_id,
            output_dir=Path(output_dir),
            mcp_command=mcp_command,
            include_screenshot=screenshot,
            mcp_protocol_version=mcp_protocol_version,
            post_launch_settle_s=post_launch_settle,
            max_steps=max_steps,
            tap_ambiguity_strategy=ambiguity_strategy,
            tap_max_target_suggestions=max_target_suggestions,
            tap_show_target_regions=show_target_regions,
            tap_prefer_target_kind=prefer_target_kind,
        )
    except ScenarioRunLaunchError as e:
        typer.echo(f"scenario-run failed (launch_app): {e}", err=True)
        raise typer.Exit(code=1) from e
    except ScenarioRunBlockingPopupError as e:
        typer.echo(f"scenario-run failed (blocking dialog): {e}", err=True)
        raise typer.Exit(code=1) from e
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        ValueError,
        EOFError,
        MaestroIntegrationError,
        HierarchyParseError,
    ) as e:
        typer.echo(f"scenario-run failed: {e}", err=True)
        raise typer.Exit(code=1) from e


if __name__ == "__main__":
    app()
