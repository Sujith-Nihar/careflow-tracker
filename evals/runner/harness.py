"""Drive a real Vogent browser call with synthetic caller audio.

What makes this a real voice evaluation rather than a transcript test: the caller's
lines are rendered to audio, played into a fake microphone, and sent to Vogent over
WebRTC. Vogent's own speech recognition, flow engine, function calls and speech
output all run for real. Nothing is stubbed on the Vogent side.

Turn-taking is deliberately conservative. The harness waits for the agent's text to
stop changing before it speaks, so it never talks over the agent, which would make
a failure look like a flow bug when it was really a harness bug.
"""

from __future__ import annotations

import http.server
import socketserver
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .scenarios import Scenario
from .tts import CACHE_DIR, render_scenario
from .vogent import Dial

PAGE_DIR = Path(__file__).resolve().parents[1] / "caller_page"

#: How long the agent's latest utterance must stay unchanged before the caller
#: replies. Long enough that a pause mid-sentence is not mistaken for a turn end.
SETTLE_SECONDS = 1.6
POLL_SECONDS = 0.3
#: Hard ceiling per call, independent of the Vogent-side timeout. Protects the
#: budget if the agent and the harness end up waiting on each other.
MAX_CALL_SECONDS = 100

#: If the agent has not said anything by now, the caller opens the conversation.
#: Waiting for the other side to speak first is how the first run burned 150
#: seconds of billed silence: the agent was waiting for the caller and the caller
#: was waiting for the agent. A real caller would just start talking.
OPEN_AFTER_SILENCE_SECONDS = 6.0

#: Give up early when the call is clearly going nowhere, rather than paying for
#: the full ceiling. Two spoken lines with no reply at all means something is
#: broken, and a longer wait will not diagnose it any better.
ABANDON_AFTER_SILENT_SECONDS = 35.0

#: How often the caller may fall back to restating their goal. Beyond this the
#: agent is looping, and a real caller would stop repeating themselves. Continuing
#: only keeps a dead call alive and billing.
MAX_FALLBACK_REPEATS = 2

#: When no scripted trigger matches, the caller stays quiet for this long before
#: restating anything. The agent pauses while its functions run, and a caller who
#: fills that pause derails the flow: observed on scenario C, where speaking during
#: the post-transfer sequence sent the agent back to attempting the transfer again.
#: Silence is the correct behaviour while the other side is working.
STALL_SECONDS = 9.0


@dataclass
class CallOutcome:
    dial_id: str
    status: str
    transcript: list[dict] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    turns_taken: int = 0
    wall_seconds: float = 0.0
    error: str | None = None

    @property
    def completed(self) -> bool:
        return self.error is None and self.turns_taken > 0


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the caller page, and the rendered clips under /clips/."""

    def translate_path(self, path: str) -> str:
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/clips/"):
            return str(CACHE_DIR / Path(clean[len("/clips/"):]).name)
        return str(PAGE_DIR / clean.lstrip("/") or "index.html")

    def log_message(self, *_args: Any) -> None:  # keep the runner's output readable
        pass


@contextmanager
def _page_server():
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()


def run_call(scenario: Scenario, dial: Dial, *, headless: bool = True) -> CallOutcome:
    """Hold one scripted conversation and return what was said and when."""
    from playwright.sync_api import sync_playwright

    lines = [t.say for t in scenario.turns] + [scenario.fallback_say]
    clips = render_scenario(lines)
    started = time.monotonic()
    outcome = CallOutcome(dial_id=dial.dial_id, status="not_started")

    with _page_server() as origin, sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-features=AudioServiceOutOfProcess",
            ],
        )
        context = browser.new_context(permissions=["microphone"])
        context.add_init_script(path=str(PAGE_DIR / "fake_mic.js"))
        page = context.new_page()
        page.goto(f"{origin}/index.html")
        page.wait_for_function("() => window.caller !== undefined", timeout=20_000)

        started_call = page.evaluate(
            "opts => window.caller.start(opts)",
            {"sessionId": dial.session_id, "dialId": dial.dial_id, "token": dial.token},
        )
        if not started_call.get("ok"):
            outcome.error = f"call did not start: {started_call.get('error')}"
            outcome.wall_seconds = round(time.monotonic() - started, 2)
            browser.close()
            return outcome

        outcome = _converse(page, scenario, clips, origin, outcome)
        snapshot = page.evaluate("() => window.caller.snapshot()")
        page.evaluate("() => window.caller.hangup()")
        outcome.transcript = snapshot.get("transcript", [])
        outcome.timeline = snapshot.get("events", [])
        outcome.status = snapshot.get("status", "unknown")
        if snapshot.get("error") and not outcome.error:
            outcome.error = snapshot["error"]
        browser.close()

    outcome.wall_seconds = round(time.monotonic() - started, 2)
    return outcome


def _converse(page, scenario: Scenario, clips: dict[str, Path], origin: str, outcome: CallOutcome):
    """Reply to the agent until the call reaches an ending or a limit."""
    import re

    started_at = time.monotonic()
    deadline = started_at + MAX_CALL_SECONDS
    spoken: set[int] = set()
    fallbacks = 0
    last_text = ""
    stable_since = None
    heard_agent = False

    while time.monotonic() < deadline and outcome.turns_taken < scenario.max_turns:
        status = page.evaluate("() => window.callerState.status")
        if status in {"ended", "error"}:
            break

        agent_lines = page.evaluate("() => window.caller.agentText()")
        text = agent_lines[-1] if agent_lines else ""
        heard_agent = heard_agent or bool(text)
        elapsed = time.monotonic() - started_at

        if not heard_agent:
            # Nothing heard yet. Open the conversation instead of waiting.
            if elapsed >= OPEN_AFTER_SILENCE_SECONDS and outcome.turns_taken == 0:
                opening = _next_line(scenario, "", spoken)
                clip = clips.get(opening or "")
                if clip is not None:
                    page.evaluate("url => window.caller.say(url)", f"{origin}/clips/{clip.name}")
                    outcome.turns_taken += 1
                    time.sleep(1.0)
                    continue
            if elapsed >= ABANDON_AFTER_SILENT_SECONDS:
                outcome.error = (
                    "the agent never spoke; abandoned early to avoid paying for silence"
                )
                break
            time.sleep(POLL_SECONDS)
            continue

        if scenario.end_when and text and re.search(scenario.end_when, text, re.IGNORECASE):
            # Let the agent finish its closing sentence before hanging up.
            time.sleep(2.0)
            break

        if text != last_text:
            last_text, stable_since = text, time.monotonic()
            time.sleep(POLL_SECONDS)
            continue

        if not text or stable_since is None or time.monotonic() - stable_since < SETTLE_SECONDS:
            time.sleep(POLL_SECONDS)
            continue

        line = _next_line(scenario, text, spoken)

        # Nothing in the script answers this. Wait: the agent is most likely mid-way
        # through its own function calls, and interrupting derails it.
        if line is None or line == scenario.fallback_say:
            if time.monotonic() - stable_since < STALL_SECONDS:
                time.sleep(POLL_SECONDS)
                continue
            line = scenario.fallback_say

        if line is None:
            time.sleep(POLL_SECONDS)
            continue

        if line == scenario.fallback_say:
            fallbacks += 1
            if fallbacks > MAX_FALLBACK_REPEATS:
                outcome.error = (
                    "the agent repeated itself and the script had nothing left to say; "
                    "stopped rather than keep a looping call alive"
                )
                break

        clip = clips.get(line)
        if clip is None:
            time.sleep(POLL_SECONDS)
            continue

        page.evaluate("url => window.caller.say(url)", f"{origin}/clips/{clip.name}")
        outcome.turns_taken += 1
        stable_since = None
        last_text = text
        time.sleep(0.8)  # let the agent begin responding before polling again

    return outcome


def _next_line(scenario: Scenario, agent_text: str, spoken: set[int]) -> str | None:
    """Pick the caller's reply: the first unused turn whose trigger matches.

    With no agent text at all, fall straight through to the first unused turn:
    that is the caller opening the conversation.
    """
    import re

    if not agent_text:
        for index, turn in enumerate(scenario.turns):
            if index not in spoken:
                spoken.add(index)
                return turn.say
        return scenario.fallback_say or None

    for index, turn in enumerate(scenario.turns):
        if index in spoken:
            continue
        if re.search(turn.when, agent_text, re.IGNORECASE):
            spoken.add(index)
            return turn.say

    # The agent said something the script did not anticipate. Restate the caller's
    # goal. Deliberately do NOT consume the next scripted turn: they are ordered,
    # and the last one is usually a closing line, so playing it out of order hangs
    # up in the middle of the task and looks like an agent failure.
    return scenario.fallback_say or None
