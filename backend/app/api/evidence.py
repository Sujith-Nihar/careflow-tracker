"""Evidence API consumed by the staff interface and the evaluator.

Both read exactly the same document, so the dashboard and the evaluator can never
disagree about what happened on a call.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from ..config import settings
from ..domain.derive_status import derive_status
from ..observability.logging import bind, get_logger
from ..persistence import repositories as repo
from ..persistence.db import query_one, transaction
from ..services.status import as_dict, derive_for_call
from . import auth
from .schemas import (
    EvaluationCaseRequest,
    EvaluationRunClose,
    EvaluationRunRequest,
    RegisterDialRequest,
    StaffActionRequest,
)
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
            conn,
            dial_id=body.dial_id,
            organization_id=principal.organization_id,
            scenario_id=body.scenario_id,
            scenario_version=body.scenario_version,
            evaluation_run_id=body.evaluation_run_id,
            true_intent=body.true_intent,
            profile=body.fault_profile,
        )
        call = repo.get_or_create_call(
            conn, organization_id=principal.organization_id, dial_id=body.dial_id
        )
        if body.agent_version:
            repo.set_agent_version(conn, body.dial_id, body.agent_version)
        log.info(
            "eval.dial_registered",
            dial_id=body.dial_id,
            scenario_id=body.scenario_id,
            evaluation_run_id=body.evaluation_run_id,
            call_id=str(call["id"]),
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
                    "agent_promised": _promise_summary(evidence),
                    "agent_version": row.get("agent_version"),
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


#: What the agent told the caller, in the order we would want to read it. Only the
#: claims matter for the list; the honest disclosures are shown on the detail page.
_PROMISE_TEXT = {
    "promised_transfer": "A transfer to the nurse",
    "promised_callback": "A callback from the nurse",
    "promised_appointment": "An appointment",
}


def _promise_summary(evidence) -> str | None:
    """One short phrase for what the agent told the caller it had arranged."""
    for kind, text in _PROMISE_TEXT.items():
        if any(str(s.kind) == kind for s in evidence.agent_statements):
            return text
    disposition = next(
        (s for s in evidence.agent_statements if str(s.kind) == "reported_disposition"), None
    )
    if disposition is not None and disposition.disposition is not None:
        return f"Reported it as {str(disposition.disposition).replace('_', ' ')}"
    return None


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
                    "agent_version": row.get("agent_version"),
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
                        "kind": str(s.kind),
                        "source": str(s.source),
                        "disposition": str(s.disposition) if s.disposition else None,
                        "evidence_text": s.evidence_text,
                        "sequence_no": s.sequence_no,
                        "observed_at": _iso(s.observed_at),
                    }
                    for s in evidence.agent_statements
                ],
                "action_executions": [
                    {
                        "id": str(e["id"]),
                        "kind": e["kind"],
                        "outcome": e["outcome"],
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
                        {
                            "id": a.id,
                            "status": str(a.status),
                            "action_execution_id": a.action_execution_id,
                        }
                        for a in evidence.appointments
                    ],
                    "transfer_sessions": [
                        {
                            "id": t.id,
                            "status": str(t.status),
                            "failure_reason": t.failure_reason,
                            "action_execution_id": t.action_execution_id,
                        }
                        for t in evidence.transfer_sessions
                    ],
                    "callback_requests": [
                        {
                            "id": c.id,
                            "status": str(c.status),
                            "priority": str(c.priority),
                            "action_execution_id": c.action_execution_id,
                        }
                        for c in evidence.callback_requests
                    ],
                },
                "staff_actions": [
                    {
                        "id": s.id,
                        "kind": str(s.kind),
                        "actor": s.actor,
                        "created_at": _iso(s.created_at),
                    }
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
        return jsonify(
            {"lifecycle": lifecycle, "derived": as_dict(derived) if derived else None}
        ), 200


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
                conn,
                callback_id=body.target_callback_id,
                organization_id=principal.organization_id,
                actor=body.actor,
            )
            if completed is None:
                return jsonify({"error": "callback_not_open"}), 409

        repo.insert_staff_action(
            conn,
            call_id=call_id,
            organization_id=principal.organization_id,
            actor=body.actor,
            kind=body.kind,
            target_callback_id=body.target_callback_id,
            note=body.note,
        )
        derived = derive_for_call(conn, call_id, principal.organization_id)
        log.info("staff.action_recorded", call_id=call_id, kind=body.kind)
        return jsonify({"derived": as_dict(derived) if derived else None}), 201


@bp.post("/evaluation-runs")
def open_evaluation_run() -> Any:
    """Open an evaluation run.

    Runs are persisted, not just written to disk, so a result can be queried
    alongside the calls it produced and an async worker has somewhere to report to.
    """
    try:
        body = EvaluationRunRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({"error": "invalid_request", "request_id": g.get("request_id")}), 400

    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        run = repo.create_evaluation_run(
            conn, organization_id=principal.organization_id, suite=body.suite,
            strategy=body.strategy, versioned_prompt_id=body.versioned_prompt_id,
            backend_git_sha=body.backend_git_sha, rate_usd_per_second=body.rate_usd_per_second,
            rate_source=body.rate_source, cost_label=body.cost_label, job_id=body.job_id,
            run_id=body.run_id,
        )
        log.info(
            "evaluation.run.started", evaluation_run_id=str(run["id"]), strategy=body.strategy,
            versioned_prompt_id=body.versioned_prompt_id,
        )
        return jsonify({"evaluation_run_id": str(run["id"])}), 201


@bp.post("/evaluation-runs/<run_id>/cases")
def record_case(run_id: str) -> Any:
    """Record one scenario's outcome within a run."""
    try:
        body = EvaluationCaseRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({"error": "invalid_request", "request_id": g.get("request_id")}), 400

    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        repo.record_evaluation_case(
            conn, run_id=run_id, organization_id=principal.organization_id,
            scenario_id=body.scenario_id, scenario_version=body.scenario_version,
            mode=body.mode, passed=body.passed, metrics=body.metrics, dial_id=body.dial_id,
            call_id=body.call_id, wall_seconds=body.wall_seconds,
            connected_seconds=body.connected_seconds, cost_usd=body.cost_usd,
            artifact_path=body.artifact_path, cache_key=body.cache_key,
        )
        log.info(
            "evaluation.case.completed", evaluation_run_id=run_id, scenario_id=body.scenario_id,
            mode=body.mode, passed=bool(body.passed), connected_seconds=body.connected_seconds,
        )
        return jsonify({"recorded": True}), 201


@bp.patch("/evaluation-runs/<run_id>")
def close_run(run_id: str) -> Any:
    """Close a run as completed or failed."""
    try:
        body = EvaluationRunClose.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify({"error": "invalid_request", "request_id": g.get("request_id")}), 400

    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        repo.close_evaluation_run(
            conn, run_id=run_id, organization_id=principal.organization_id,
            status=body.status, wall_seconds=body.wall_seconds, error=body.error,
        )
        log.info(
            f"evaluation.run.{body.status}", evaluation_run_id=run_id,
            wall_seconds=body.wall_seconds,
        )
        return jsonify({"closed": True}), 200


@bp.get("/evaluation-runs/<run_id>")
def get_run(run_id: str) -> Any:
    """A run and every case within it."""
    with transaction() as conn:
        principal = auth.from_organization_header(conn, request)
        run = repo.get_evaluation_run(conn, run_id, principal.organization_id)
        if run is None:
            return jsonify({"error": "not_found", "request_id": g.get("request_id")}), 404
        return jsonify(_serialise(run)), 200


def _serialise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


@bp.get("/healthz")
def healthz() -> Any:
    with transaction() as conn:
        ok = query_one(conn, "SELECT 1 AS ok") is not None
    return jsonify({"ok": ok, "git_sha": settings().git_sha}), 200 if ok else 503


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None
