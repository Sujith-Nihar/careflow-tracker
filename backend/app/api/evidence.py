"""Evidence API consumed by the staff interface and the evaluator.

Both read exactly the same document, so the dashboard and the evaluator can never
disagree about what happened on a call.
"""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from ..config import settings
from ..observability.logging import bind, get_logger
from ..persistence import repositories as repo
from ..persistence.db import query_one, transaction
from ..domain.derive_status import derive_status
from ..services.status import as_dict, derive_for_call
from . import auth
from .schemas import RegisterDialRequest, StaffActionRequest
from .vogent_webhooks import sync_dial_record

bp = Blueprint("evidence", __name__, url_prefix="/api")
log = get_logger(__name__)


@bp.post("/eval/dials")
def register_dial() -> Any:
    """Register a dial and its fault profile before the call starts.

    The scenario and its injected failures are bound to the dial id here, so
    simulator behaviour never depends on the model repeating a scenario name.
    """
    try:
        body = RegisterDialRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid_request", "detail": exc.error_count()}), 400

    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        repo.register_fault_profile(
            conn, dial_id=body.dial_id, organization_id=principal.organization_id,
            scenario_id=body.scenario_id, scenario_version=body.scenario_version,
            evaluation_run_id=body.evaluation_run_id, true_intent=body.true_intent,
            profile=body.fault_profile,
        )
        call = repo.get_or_create_call(
            conn, organization_id=principal.organization_id, dial_id=body.dial_id
        )
        log.info(
            "eval.dial_registered", dial_id=body.dial_id, scenario_id=body.scenario_id,
            evaluation_run_id=body.evaluation_run_id, call_id=str(call["id"]),
        )
        return jsonify({"call_id": str(call["id"]), "dial_id": body.dial_id}), 201


@bp.get("/calls")
def list_calls() -> Any:
    """Calls for the attention list, most urgent first.

    Ordering is by derived severity, not by anything stored, so the list cannot
    drift from the reasons shown on the detail page.
    """
    only_attention = request.args.get("requires_staff_action", "").lower() in {"1", "true", "yes"}
    limit = min(int(request.args.get("limit", 100)), 500)

    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        bind(organization_id=principal.organization_id)
        rows = repo.calls_for_attention(conn, principal.organization_id, limit=limit)
        bundles = repo.load_evidence_bulk(
            conn, [str(r["id"]) for r in rows], principal.organization_id
        )

        items = []
        for row in rows:
            evidence = bundles.get(str(row["id"]))
            if evidence is None:
                continue
            derived = derive_status(evidence)
            if only_attention and not derived.requires_staff_action:
                continue
            items.append(
                {
                    "call_id": str(row["id"]),
                    "dial_id": row["dial_id"],
                    "scenario_id": row["scenario_id"],
                    "lifecycle": row["lifecycle"],
                    "started_at": _iso(row["started_at"]),
                    "ended_at": _iso(row["ended_at"]),
                    "connected_seconds": row["connected_seconds"],
                    "agent_classified_intent": row["agent_classified_intent"],
                    "derived": as_dict(derived),
                }
            )

        items.sort(key=lambda i: (-i["derived"]["severity"], i["ended_at"] or ""))
        return jsonify({"calls": items, "count": len(items)}), 200


@bp.get("/calls/by-dial/<dial_id>")
def get_call_by_dial(dial_id: str) -> Any:
    """Resolve a Vogent dial to a call, for tracing a run back to its evidence."""
    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        row = repo.get_call_by_dial(conn, dial_id, principal.organization_id)
        if row is None:
            return jsonify({"error": "not_found", "request_id": g.get("request_id")}), 404
        return jsonify({"call_id": str(row["id"])}), 200


@bp.get("/calls/<call_id>")
def get_call(call_id: str) -> Any:
    """The full evidence bundle for one call."""
    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        bind(organization_id=principal.organization_id, call_id=call_id)

        row = repo.get_call(conn, call_id, principal.organization_id)
        if row is None:
            # Not found and not-yours are the same answer, so the endpoint cannot
            # be used to discover which call ids exist in another practice.
            return jsonify({"error": "not_found", "request_id": g.get("request_id")}), 404

        evidence = repo.load_evidence(conn, call_id, principal.organization_id)
        derived = derive_for_call(conn, call_id, principal.organization_id)
        raw = repo.raw_evidence_rows(conn, call_id, principal.organization_id)

        return jsonify(
            {
                "call": {
                    "id": str(row["id"]),
                    "dial_id": row["dial_id"],
                    "vogent_agent_id": row["vogent_agent_id"],
                    "versioned_prompt_id": row["versioned_prompt_id"],
                    "scenario_id": row["scenario_id"],
                    "evaluation_run_id": _str_or_none(row["evaluation_run_id"]),
                    "lifecycle": row["lifecycle"],
                    "started_at": _iso(row["started_at"]),
                    "ended_at": _iso(row["ended_at"]),
                    "connected_seconds": row["connected_seconds"],
                    "system_result_type": row["system_result_type"],
                },
                "intent": {
                    "agent_classified": row["agent_classified_intent"],
                    "true_intent": row["true_intent"],
                },
                "agent_statements": [
                    {
                        "kind": str(s.kind), "source": str(s.source),
                        "disposition": str(s.disposition) if s.disposition else None,
                        "evidence_text": s.evidence_text, "sequence_no": s.sequence_no,
                        "observed_at": _iso(s.observed_at),
                    }
                    for s in evidence.agent_statements
                ],
                "action_executions": [
                    {
                        "id": str(e["id"]), "kind": e["kind"], "outcome": e["outcome"],
                        "request_payload": e["request_payload"],
                        "response_payload": e["response_payload"],
                        "attempts": e["attempts"],
                        "downstream_ref": e["downstream_ref"],
                        "duplicate_of_id": _str_or_none(e["duplicate_of_id"]),
                        "requested_at": _iso(e["requested_at"]),
                        "completed_at": _iso(e["completed_at"]),
                    }
                    for e in raw["action_executions"]
                ],
                "downstream": {
                    "appointments": [
                        {"id": a.id, "status": str(a.status),
                         "action_execution_id": a.action_execution_id}
                        for a in evidence.appointments
                    ],
                    "transfer_sessions": [
                        {"id": t.id, "status": str(t.status), "failure_reason": t.failure_reason,
                         "action_execution_id": t.action_execution_id}
                        for t in evidence.transfer_sessions
                    ],
                    "callback_requests": [
                        {"id": c.id, "status": str(c.status), "priority": str(c.priority),
                         "action_execution_id": c.action_execution_id}
                        for c in evidence.callback_requests
                    ],
                },
                "staff_actions": [
                    {"id": s.id, "kind": str(s.kind), "actor": s.actor,
                     "created_at": _iso(s.created_at)}
                    for s in evidence.staff_actions
                ],
                "derived": as_dict(derived) if derived else None,
                "transcript": {
                    "authoritative": False,
                    "note": "Shows what was said, not what happened.",
                    "segments": row["transcript"] or [],
                },
            }
        ), 200


@bp.post("/calls/<call_id>/sync-dial")
def sync_dial(call_id: str) -> Any:
    """Fetch the dial record now, rather than waiting for a webhook."""
    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        row = repo.get_call(conn, call_id, principal.organization_id)
        if row is None:
            return jsonify({"error": "not_found", "request_id": g.get("request_id")}), 404
        lifecycle = sync_dial_record(conn, row, principal)
        derived = derive_for_call(conn, call_id, principal.organization_id)
        return jsonify({"lifecycle": lifecycle, "derived": as_dict(derived) if derived else None}), 200


@bp.post("/calls/<call_id>/staff-actions")
def add_staff_action(call_id: str) -> Any:
    """Record that a human dealt with the call."""
    try:
        body = StaffActionRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({"error": "invalid_request", "request_id": g.get("request_id")}), 400

    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        row = repo.get_call(conn, call_id, principal.organization_id)
        if row is None:
            return jsonify({"error": "not_found", "request_id": g.get("request_id")}), 404

        if body.kind == "callback_completed":
            if not body.target_callback_id:
                return jsonify({"error": "target_callback_id_required"}), 400
            completed = repo.complete_callback(
                conn, callback_id=body.target_callback_id,
                organization_id=principal.organization_id, actor=body.actor,
            )
            if completed is None:
                return jsonify({"error": "callback_not_open"}), 409

        repo.insert_staff_action(
            conn, call_id=call_id, organization_id=principal.organization_id, actor=body.actor,
            kind=body.kind, target_callback_id=body.target_callback_id, note=body.note,
        )
        derived = derive_for_call(conn, call_id, principal.organization_id)
        log.info("staff.action_recorded", call_id=call_id, kind=body.kind)
        return jsonify({"derived": as_dict(derived) if derived else None}), 201


@bp.get("/healthz")
def healthz() -> Any:
    with transaction() as conn:
        ok = query_one(conn, "SELECT 1 AS ok") is not None
    return jsonify({"ok": ok, "git_sha": settings().git_sha}), 200 if ok else 503


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
