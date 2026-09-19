"""Render the synthetic caller's lines to audio.

Uses the macOS speech synthesiser, so the caller's voice costs nothing and is
byte-identical between runs. That matters twice over: the cost experiment can
attribute every dollar to Vogent alone, and a re-run of a scenario feeds the
agent exactly the same audio it heard last time.

Clips are cached by (voice, rate, text), so only new or changed lines are rendered.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "clips"

#: A plain, clearly-articulated system voice. The point is to exercise Vogent's
#: speech recognition with real audio, not to imitate a specific person.
DEFAULT_VOICE = "Samantha"
DEFAULT_RATE = 175  # words per minute; close to unhurried natural speech
SAMPLE_RATE = 24000


class SpeechUnavailable(RuntimeError):
    pass


def ensure_available() -> None:
    if shutil.which("say") is None:
        raise SpeechUnavailable(
            "the macOS `say` command is required to render the synthetic caller"
        )


def clip_for(
    text: str, *, voice: str = DEFAULT_VOICE, rate: int = DEFAULT_RATE
) -> Path:
    """Return a WAV file for this line, rendering it only if not already cached."""
    ensure_available()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(
        f"{voice}|{rate}|{SAMPLE_RATE}|{text}".encode()
    ).hexdigest()[:16]
    path = CACHE_DIR / f"{digest}.wav"
    if path.exists() and path.stat().st_size > 0:
        return path

    subprocess.run(
        [
            "say",
            "-v",
            voice,
            "-r",
            str(rate),
            "-o",
            str(path),
            f"--data-format=LEI16@{SAMPLE_RATE}",
            text,
        ],
        check=True,
        capture_output=True,
    )
    if not path.exists():
        raise SpeechUnavailable(f"`say` produced no audio for voice {voice!r}")
    return path


def render_scenario(lines: list[str], **kwargs) -> dict[str, Path]:
    """Pre-render every line a scenario might need, before the call starts.

    Rendering mid-call would add a pause the agent would hear as hesitation, and
    would put local CPU time inside the measured connected seconds.
    """
    return {line: clip_for(line, **kwargs) for line in lines if line.strip()}
