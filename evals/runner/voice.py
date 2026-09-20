"""Run a scenario as a real Vogent browser voice call and score it.

The ordering matters and is deliberate:
  1. create the dial, so a dial id exists
  2. register the dial and its fault profile with the backend, BEFORE any audio
  3. hold the conversation
  4. read the authoritative dial record back from Vogent
  5. read the evidence bundle from the backend and score it

Step 2 before step 3 is what stops simulator behaviour depending on the model
relaying a scenario name correctly. Step 4 before step 5 is what gives every case
its connected seconds and therefore its cost.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .harness import run_call
from .metrics import MetricResult, evaluate
from .replay import BackendClient
from .scenarios import Scenario
from .vogent import VogentClient, webhook_url_for_backend

#: Standard-voice rate, docs.vogent.ai/platform-overview/billing, read 2026-09-18.
#: Every dollar figure derived from it is a CALCULATED_ESTIMATE, never a billed charge.
DEFAULT_RATE_USD_PER_SECOND = 0.0015
COST_LABEL_ESTIMATE = "CALCULATED_ESTIMATE"


@dataclass
class VoiceCase:
    scenario_id: str
    scenario_version: int
    version: str
    versioned_prompt_id: str
    dial_id: str
    evaluation_run_id: str
    call_id: str | None = None
    passed: bool = False
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    derived_status: str | None = None
    requires_staff_action: bool | None = None
    promise_mismatch: bool | None = None
    started_at: str | None = None
    ended_at: str | None = None
    wall_seconds: float = 0.0
    connected_seconds: int | None = None
    cost_usd: float | None = None
    cost_label: str = COST_LABEL_ESTIMATE
    system_result_type: str | None = None
    turns_taken: int = 0
    error: str | None = None
    artifact_path: str | None = None


def run_voice_case(
    scenario: Scenario,
    *,
    version: str,
    run_id: str,
    backend: BackendClient,
    vogent: VogentClient,
    artifacts_root: Path,
    rate_usd_per_second: float = DEFAULT_RATE_USD_PER_SECOND,
    headless: bool = True,
) -> VoiceCase:
    started = time.monotonic()
    versioned_prompt_id = vogent.versioned_prompt_id(version)

    dial = vogent.create_browser_dial(
        versioned_prompt_id=versioned_prompt_id,
        inputs={
            "patient_ref": scenario.patient_ref,
            "callback_phone": scenario.callback_phone,
            "scenario_id": scenario.id,
            "evaluation_run_id": run_id,
        },
        webhook_url=webhook_url_for_backend(),
        idempotency_key=f"{run_id}:{version}:{scenario.id}",
    )

    case = VoiceCase(
        scenario_id=scenario.id,
        scenario_version=scenario.version,
        version=version,
        versioned_prompt_id=versioned_prompt_id,
        dial_id=dial.dial_id,
        evaluation_run_id=run_id,
    )

    # Register before any audio: the simulators must never learn the scenario
    # from the conversation.
    backend.register_dial(scenario, dial.dial_id, run_id, agent_version=version)

    outcome = run_call(scenario, dial, headless=headless)
    case.turns_taken = outcome.turns_taken
    case.error = outcome.error

    # The browser SDK's live transcript is more complete than the one Vogent stores
    # on the dial record, which truncates the agent's final utterance. Scenario D
    # recorded "The transfer did not" on the dial while the browser heard the whole
    # sentence, including the callback failure the caller needed to be told about.
    # Feed the fuller record to the backend so statements are scored from what was
    # actually said. It changes no action state: transcripts are evidence of speech.
    dial_record_early = _read_dial(vogent, dial.dial_id)
    best_transcript = _most_complete(
        outcome.transcript, dial_record_early.get("transcript") or []
    )
    if best_transcript:
        try:
            backend.send_webhook(
                "dial.transcript",
                {"dial_id": dial.dial_id, "transcript": best_transcript},
            )
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: scoring falls back to the vendor's transcript, which is
            # less complete. Recorded on the case so a reviewer can see that the
            # truthfulness metrics were scored from the weaker source.
            case.error = f"browser transcript not delivered ({type(exc).__name__})"

    dial_record = dial_record_early or _read_dial(vogent, dial.dial_id)
    case.connected_seconds = _connected_seconds(dial_record)
    case.started_at = dial_record.get("startedAt")
    case.ended_at = dial_record.get("endedAt")
    case.system_result_type = dial_record.get("systemResultType")
    if case.connected_seconds is not None:
        case.cost_usd = round(case.connected_seconds * rate_usd_per_second, 6)

    bundle = _read_bundle(backend, dial.dial_id)
    if bundle is not None:
        case.call_id = (bundle.get("call") or {}).get("id")
        derived = bundle.get("derived") or {}
        case.derived_status = derived.get("status")
        case.requires_staff_action = derived.get("requires_staff_action")
        case.promise_mismatch = derived.get("promise_mismatch")
        result: MetricResult = evaluate(scenario, bundle, dial=dial_record)
        case.passed = result.passed
        case.failures = result.failures
        case.metrics = result.values
    else:
        case.error = case.error or "no evidence bundle for this dial"

    case.wall_seconds = round(time.monotonic() - started, 2)
    case.artifact_path = str(
        _write_artifacts(artifacts_root, case, scenario, outcome, dial_record, bundle)
    )
    return case


def _most_complete(browser: list[dict], vendor: list[dict]) -> list[dict]:
    """Pick the fuller of the two transcripts of the same call.

    Neither source is reliably complete. The vendor's stored copy truncates the final
    utterance; the browser's live copy sometimes stops updating when the call ends
    mid-sentence, and which one wins varies run to run. Both describe the same call,
    so taking whichever holds more spoken text is safe and strictly better than
    trusting either alone.

    This affects only what was *said*. Action state is untouched by it, and remains
    the thing that decides whether a caller was helped.
    """

    def spoken(segments: list[dict]) -> int:
        return sum(len(str(s.get("text") or "")) for s in segments)

    return (
        browser
        if spoken(browser) >= spoken(vendor)
        else [{"speaker": s.get("speaker"), "text": s.get("text")} for s in vendor]
    )


def _read_dial(vogent: VogentClient, dial_id: str, *, attempts: int = 8) -> dict:
    """Poll until the dial record is finalised, then keep reading while it grows.

    `endedAt` appears before the transcript finishes being written. Returning on
    the first sight of it truncates the agent's closing sentence, which is exactly
    the sentence the truthfulness checks depend on: scenario D once recorded only
    "The transfer" and failed its disclosure check on a call that was otherwise
    correct. So once the call has ended, keep re-reading until the transcript
    stops growing.
    """
    record: dict = {}
    for attempt in range(attempts):
        try:
            record = vogent.get_dial(dial_id)
        except Exception:  # noqa: BLE001 - a transient read must not lose the run
            record = record or {}
        if record.get("endedAt"):
            break
        time.sleep(2 + attempt)

    if not record.get("endedAt"):
        return record

    best = record
    for _ in range(4):
        time.sleep(3)
        try:
            candidate = vogent.get_dial(dial_id)
        except Exception:  # noqa: BLE001
            # A transient read failure must not lose an expensive completed call.
            # Keep the best record so far and stop growing it.
            break
        if _transcript_length(candidate) > _transcript_length(best):
            best = candidate
        else:
            break
    return best


def _transcript_length(record: dict) -> int:
    """Total characters spoken, which grows as the vendor finishes writing."""
    return sum(len(str(s.get("text") or "")) for s in (record.get("transcript") or []))


def _connected_seconds(dial_record: dict) -> int | None:
    for key in ("aiDurationSeconds", "durationSeconds"):
        value = dial_record.get(key)
        if isinstance(value, int | float):
            return int(value)
    return None


def _read_bundle(
    backend: BackendClient, dial_id: str, *, attempts: int = 6
) -> dict | None:
    """Give late webhooks a moment, then ask the backend to finalise if needed."""
    for attempt in range(attempts):
        try:
            bundle = backend.bundle_for_dial(dial_id)
        except Exception:  # noqa: BLE001
            time.sleep(2)
            continue
        lifecycle = (bundle.get("call") or {}).get("lifecycle")
        if lifecycle in {"ended", "ended_unconfirmed"}:
            return bundle
        if attempt == attempts - 2:
            call_id = (bundle.get("call") or {}).get("id")
            if call_id:
                backend.sync_dial(call_id)
        time.sleep(3)
    try:
        return backend.bundle_for_dial(dial_id)
    except Exception:  # noqa: BLE001
        return None


def _write_artifacts(
    root: Path,
    case: VoiceCase,
    scenario: Scenario,
    outcome,
    dial_record: dict,
    bundle: dict | None,
) -> Path:
    directory = root / case.evaluation_run_id / case.scenario_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dial.json").write_text(json.dumps(dial_record, indent=2, default=str))
    (directory / "transcript.json").write_text(json.dumps(outcome.transcript, indent=2))
    (directory / "timeline.json").write_text(json.dumps(outcome.timeline, indent=2))
    if bundle is not None:
        (directory / "evidence.json").write_text(
            json.dumps(bundle, indent=2, default=str)
        )
    (directory / "metrics.json").write_text(
        json.dumps(asdict(case), indent=2, default=str)
    )
    return directory
