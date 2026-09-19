"""Request validation for the Vogent-facing boundary.

Bounds are tight on purpose. These fields carry whatever a speech model produced,
so an unbounded string is both a storage risk and a signal that something went
wrong upstream. Unknown keys are ignored rather than stored.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_SHORT = 200
MAX_REASON = 500
MAX_SUMMARY = 300


class Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class FunctionEnvelope(Strict):
    """The body Vogent posts to an API function."""

    dial_id: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    dial: dict[str, Any] = Field(default_factory=dict)

    @property
    def vogent_agent_id(self) -> str | None:
        agent = self.dial.get("agent")
        return str(agent.get("id")) if isinstance(agent, dict) and agent.get("id") else None

    @property
    def versioned_prompt_id(self) -> str | None:
        value = self.dial.get("versionedPromptId")
        return str(value) if value else None

    @property
    def dial_inputs(self) -> dict[str, Any]:
        """`callAgentInput` echoed back on the dial, set when the dial was created."""
        value = self.dial.get("inputs")
        return value if isinstance(value, dict) else {}

    def resolved(self, name: str, spoken: str) -> str:
        """Prefer a value set at dial creation over one the model supplied.

        A flow template such as `{{patient_ref}}` may arrive unresolved, and a
        value the model repeated back may be misheard. Identifiers fixed when the
        dial was created are more trustworthy than either.
        """
        fixed = str(self.dial_inputs.get(name) or "").strip()
        spoken = (spoken or "").strip()
        if spoken.startswith("{{") or not spoken:
            return fixed or spoken
        return fixed or spoken

    @property
    def transcript_snapshot(self) -> list | None:
        value = self.dial.get("transcript")
        return value if isinstance(value, list) and value else None


class ScheduleAppointmentParams(Strict):
    patient_ref: str = Field(default="", max_length=64)
    preferred_date: str = Field(default="", max_length=MAX_SHORT)
    reason: str = Field(default="", max_length=MAX_REASON)


class TransferTriageParams(Strict):
    patient_ref: str = Field(default="", max_length=64)
    concern_summary: str = Field(default="", max_length=MAX_REASON)
    callback_phone: str = Field(default="", max_length=MAX_SHORT)


class CreateCallbackParams(Strict):
    patient_ref: str = Field(default="", max_length=64)
    callback_phone: str = Field(default="", max_length=MAX_SHORT)
    priority: Literal["urgent", "normal"] = "urgent"
    reason_code: Literal["transfer_failed", "unsupported_request", "caller_requested"] = (
        "transfer_failed"
    )

    @field_validator("priority", "reason_code", mode="before")
    @classmethod
    def _lowercase(cls, value: Any) -> Any:
        return value.strip().lower() if isinstance(value, str) else value


class ReportDispositionParams(Strict):
    category: Literal["routine_scheduling", "post_operative_concern", "other"] = "other"
    disposition: Literal[
        "scheduled",
        "transferred",
        "callback_pending",
        "escalation_failed",
        "unresolved",
        "resolved",
    ] = "unresolved"
    summary: str = Field(default="", max_length=MAX_SUMMARY)

    @field_validator("category", "disposition", mode="before")
    @classmethod
    def _lowercase(cls, value: Any) -> Any:
        return value.strip().lower().replace(" ", "_") if isinstance(value, str) else value


class RegisterDialRequest(Strict):
    dial_id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(min_length=1, max_length=128)
    scenario_version: int = 1
    evaluation_run_id: str | None = None
    true_intent: str | None = None
    fault_profile: dict[str, str] = Field(default_factory=dict)


class EvaluationRunRequest(Strict):
    run_id: str | None = None
    suite: str = Field(default="careflow", max_length=64)
    strategy: Literal["naive_voice", "optimized", "replay"]
    versioned_prompt_id: str | None = Field(default=None, max_length=128)
    backend_git_sha: str | None = Field(default=None, max_length=64)
    rate_usd_per_second: float | None = None
    rate_source: str | None = Field(default=None, max_length=256)
    cost_label: Literal["ACTUAL_BILLED", "CALCULATED_ESTIMATE"] = "CALCULATED_ESTIMATE"
    job_id: str | None = Field(default=None, max_length=128)


class EvaluationRunClose(Strict):
    status: Literal["completed", "failed"]
    wall_seconds: float | None = None
    error: str | None = Field(default=None, max_length=2000)


class EvaluationCaseRequest(Strict):
    scenario_id: str = Field(min_length=1, max_length=128)
    scenario_version: int = 1
    mode: Literal["voice", "replay", "structural"]
    passed: bool | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    dial_id: str | None = Field(default=None, max_length=128)
    call_id: str | None = None
    wall_seconds: float | None = None
    connected_seconds: int | None = None
    cost_usd: float | None = None
    artifact_path: str | None = Field(default=None, max_length=512)
    cache_key: str | None = Field(default=None, max_length=256)


class StaffActionRequest(Strict):
    kind: Literal["callback_completed", "reviewed"]
    actor: str = Field(min_length=1, max_length=120)
    target_callback_id: str | None = None
    note: str | None = Field(default=None, max_length=1000)


__all__ = [
    "CreateCallbackParams",
    "FunctionEnvelope",
    "RegisterDialRequest",
    "ReportDispositionParams",
    "ScheduleAppointmentParams",
    "StaffActionRequest",
    "TransferTriageParams",
    "ValidationError",
]
