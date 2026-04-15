"""Structured logging configuration (stdlib + structlog)."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, level: str = "INFO", json_format: bool = False) -> None:
    """Configure structlog and the stdlib logging root for consistent structured output."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", key="timestamp", utc=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        formatter: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        formatter = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                formatter,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog-bound stdlib logger."""
    return structlog.get_logger(name)
