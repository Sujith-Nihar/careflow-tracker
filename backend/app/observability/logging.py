"""Structured JSON logging with an allow-list.

Healthcare context: assume every free-text field is sensitive even though this
project's data is synthetic. Only identifiers and enum-like values may be logged.
Anything not on the allow-list is dropped rather than truncated, so a new field
cannot leak by accident.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

#: The only keys permitted in a log line. Adding a key here is a deliberate act.
ALLOWED_FIELDS = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "logger",
        # correlation
        "request_id",
        "organization_id",
        "call_id",
        "dial_id",
        "action_execution_id",
        "scenario_id",
        "evaluation_run_id",
        "job_id",
        "versioned_prompt_id",
        "vogent_agent_id",
        # classification and outcome, all enum-like
        "function",
        "kind",
        "outcome",
        "status",
        "lifecycle",
        "severity",
        "mode",
        "strategy",
        "duplicate",
        "attempt_no",
        "latency_ms",
        "http_status",
        "reason_code",
        "event_type",
        "requires_staff_action",
        "promise_mismatch",
        "connected_seconds",
        "system_result_type",
        "passed",
        "receive_count",
        "count",
        "rules_version",
        "error_type",
    }
)

#: Free-text and payload fields that must never reach a log, named so the
#: redaction is visible to a reviewer rather than implied.
DENIED_FIELDS = frozenset(
    {
        "params",
        "payload",
        "request_payload",
        "response_payload",
        "transcript",
        "evidence_text",
        "callback_phone",
        "patient_ref",
        "concern_summary",
        "reason",
        "summary",
        "token",
        "api_key",
        "authorization",
        "dial",
        "note",
        "actor",
    }
)

#: Defaults to None, never to a shared dict. A mutable ContextVar default is a single
#: object shared by every context, so one request mutating it would leak its
#: correlation fields into another request's log lines.
_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def bind(**fields: Any) -> None:
    """Attach correlation fields to every subsequent log line in this request."""
    current = _context.get() or {}
    _context.set({**current, **{k: v for k, v in fields.items() if v is not None}})


def clear() -> None:
    _context.set(None)


def _merge_context(_logger, _name, event_dict: dict) -> dict:
    return {**(_context.get() or {}), **event_dict}


def _enforce_allow_list(_logger, _name, event_dict: dict) -> dict:
    kept = {}
    dropped: list[str] = []
    for key, value in event_dict.items():
        if key in ALLOWED_FIELDS:
            kept[key] = value
        else:
            dropped.append(key)
    if dropped:
        # Name the dropped keys, never their values, so redaction is auditable.
        kept["dropped_fields"] = sorted(dropped)
        # `dropped_fields` is itself allowed only through this path.
    return kept


def configure(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _merge_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _enforce_allow_list,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "careflow"):
    return structlog.get_logger(name)
