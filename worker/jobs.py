"""The job contract between whoever enqueues work and the worker that runs it."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class InvalidJob(Exception):
    """The message is not a job this worker can run.

    Raised for a malformed body or an unknown scenario. The worker lets this reach a
    controlled failure rather than retrying: a job asking for a scenario that does not
    exist will never succeed, so retrying it three times only delays the dead-letter
    queue and hides the real problem.
    """


@dataclass(frozen=True, slots=True)
class EvaluationJob:
    job_id: str
    scenario_ids: list[str]
    #: Only replay runs here. A voice run needs a browser and a Vogent workspace, which
    #: a headless container in a private subnet does not have. Stated as a boundary
    #: rather than discovered in production.
    mode: str = "replay"
    suite: str = "careflow"
    evaluation_run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, body: str) -> EvaluationJob:
        try:
            raw = json.loads(body)
        except json.JSONDecodeError as exc:
            raise InvalidJob(f"body is not JSON: {exc.msg}") from exc
        if not isinstance(raw, dict):
            raise InvalidJob("body is not a JSON object")

        job_id = str(raw.get("job_id") or "").strip()
        if not job_id:
            raise InvalidJob("job_id is required")

        scenario_ids = raw.get("scenario_ids")
        if not isinstance(scenario_ids, list) or not scenario_ids:
            raise InvalidJob("scenario_ids must be a non-empty list")

        mode = str(raw.get("mode") or "replay")
        if mode != "replay":
            raise InvalidJob(f"mode {mode!r} is not runnable by this worker")

        return cls(
            job_id=job_id,
            scenario_ids=[str(s) for s in scenario_ids],
            mode=mode,
            suite=str(raw.get("suite") or "careflow"),
            evaluation_run_id=raw.get("evaluation_run_id"),
            metadata=raw.get("metadata") or {},
        )

    def as_body(self) -> str:
        return json.dumps(
            {
                "job_id": self.job_id,
                "scenario_ids": self.scenario_ids,
                "mode": self.mode,
                "suite": self.suite,
                "evaluation_run_id": self.evaluation_run_id,
                "metadata": self.metadata,
            }
        )
