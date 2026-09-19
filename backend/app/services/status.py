"""Derivation as a service: load the evidence, decide, log the decision."""

from __future__ import annotations

import psycopg

from ..domain.derive_status import derive_status
from ..domain.types import DerivedStatus
from ..observability.logging import get_logger
from ..persistence import repositories as repo

log = get_logger(__name__)


def derive_for_call(
    conn: psycopg.Connection, call_id: str, organization_id: str
) -> DerivedStatus | None:
    evidence = repo.load_evidence(conn, call_id, organization_id)
    if evidence is None:
        return None
    result = derive_status(evidence)
    log.info(
        "status.derived",
        call_id=call_id,
        status=str(result.status),
        severity=result.severity,
        requires_staff_action=result.requires_staff_action,
        promise_mismatch=result.promise_mismatch,
    )
    return result


def as_dict(result: DerivedStatus) -> dict:
    return {
        "status": str(result.status),
        "severity": result.severity,
        "requires_staff_action": result.requires_staff_action,
        "reason": result.reason,
        "next_step": result.next_step,
        "promise_mismatch": result.promise_mismatch,
        "mismatch_details": list(result.mismatch_details),
        "evidence_refs": result.evidence_refs,
    }
