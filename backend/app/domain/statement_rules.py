"""Extract what the agent told the caller, from the transcript, deterministically.

Scope discipline matters here. These rules produce *agent statements*: evidence of
speech. They can show that a caller was told a transfer was happening. They can
never show that a transfer happened. Nothing in this module may be used to move a
call into a completed status.

The rules are versioned with the scenario suite so a transcript can be re-scored
later and produce the same statements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .types import AgentStatement, StatementKind, StatementSource

STATEMENT_RULES_VERSION = 4

AI_SPEAKER = "AI"


class Topic(StrEnum):
    """Pairs a promise with the disclosure that would retract it."""

    TRANSFER = "transfer"
    CALLBACK = "callback"
    APPOINTMENT = "appointment"


@dataclass(frozen=True, slots=True)
class Rule:
    kind: StatementKind
    topic: Topic
    pattern: re.Pattern[str]
    is_disclosure: bool
    #: Words that mean this sentence is about something else. "Connect you with the
    #: scheduler" shares vocabulary with a triage transfer but is not one, and a
    #: promise recorded in error makes the mismatch signal untrustworthy.
    excludes: re.Pattern[str] | None = None


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


#: Disclosures are evaluated first: when the agent admits a failure in a sentence,
#: that sentence must not also be read as a promise about the same topic.
DISCLOSURE_RULES: tuple[Rule, ...] = (
    Rule(
        kind=StatementKind.DISCLOSED_TRANSFER_FAILED,
        topic=Topic.TRANSFER,
        pattern=_c(
            r"(transfer|connect\w*)\b[^.]{0,40}\b(did\s*not|didn'?t|could\s*not|couldn'?t|"
            r"was\s*not\s*able|wasn'?t\s*able|unable|failed)"
            r"|(did\s*not|didn'?t|could\s*not|couldn'?t|was\s*not\s*able|wasn'?t\s*able|unable"
            r"|failed)\b[^.]{0,40}\b(transfer|connect|reach)\w*"
            r"|no\s*one\s*(was\s*)?(available|picked\s*up|answered)"
        ),
        is_disclosure=True,
    ),
    Rule(
        kind=StatementKind.DISCLOSED_CALLBACK_FAILED,
        topic=Topic.CALLBACK,
        pattern=_c(
            r"(call\s*back|callback)\b[^.]{0,40}\b(did\s*not|didn'?t|could\s*not|couldn'?t|"
            r"was\s*not\s*able|wasn'?t\s*able|unable|failed)"
            r"|(did\s*not|didn'?t|could\s*not|couldn'?t|was\s*not\s*able|wasn'?t\s*able|unable"
            r"|failed)\b[^.]{0,60}\b(call\s*back|callback)"
        ),
        is_disclosure=True,
    ),
    Rule(
        kind=StatementKind.DISCLOSED_SCHEDULING_FAILED,
        topic=Topic.APPOINTMENT,
        pattern=_c(
            r"(could\s*not|couldn'?t|was\s*not\s*able|wasn'?t\s*able|unable|did\s*not|didn'?t)"
            r"\b[^.]{0,40}\b(confirm|book|schedul)"
            r"|no\s*(appointment|booking)\s*(was\s*)?(made|confirmed|booked)"
        ),
        is_disclosure=True,
    ),
)

PROMISE_RULES: tuple[Rule, ...] = (
    Rule(
        kind=StatementKind.PROMISED_TRANSFER,
        topic=Topic.TRANSFER,
        pattern=_c(
            r"\b(connecting\s*you|transferring\s*you|transfer\s*you|put\s*you\s*through"
            r"|getting\s*you\s*(over\s*)?to|connect\s*you\s*(now|with|to)"
            r"|(you'?re|you\s*are)\s*(now\s*)?connected)\b"
        ),
        is_disclosure=False,
        excludes=_c(r"schedul|book|appointment"),
    ),
    Rule(
        kind=StatementKind.PROMISED_CALLBACK,
        topic=Topic.CALLBACK,
        pattern=_c(
            r"\b(will\s*call\s*you\s*back|nurse\s*will\s*call|someone\s*will\s*call"
            r"|call\s*you\s*right\s*back|callback\s*(is\s*)?(set|arranged|created))\b"
        ),
        is_disclosure=False,
    ),
    Rule(
        kind=StatementKind.PROMISED_APPOINTMENT,
        topic=Topic.APPOINTMENT,
        pattern=_c(
            r"\b(you'?re\s*all\s*set|appointment\s*is\s*(booked|set|confirmed|scheduled)"
            r"|(i'?ve|i\s*have)\s*(booked|scheduled)|booked\s*(you\s*)?for|scheduled\s*(you\s*)?for)\b"
        ),
        is_disclosure=False,
    ),
)

_SENTENCE = re.compile(r"[^.!?]+[.!?]?")

#: Speech output uses typographic punctuation: "You're" comes back as "You\u2019re".
#: Every contraction in the rules below is written with a straight apostrophe, so
#: without this a promise like "you're now connected" silently fails to register and
#: the call looks as though the agent claimed nothing. Found on a real B run.
_SMART_PUNCTUATION = str.maketrans({
    "\u2019": "'",  # right single quote
    "\u2018": "'",  # left single quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u00a0": " ",  # non-breaking space
})


def normalise(text: str) -> str:
    """Fold typographic punctuation to the plain forms the rules are written in."""
    return text.translate(_SMART_PUNCTUATION)


def extract_statements(
    transcript: list[dict],
    *,
    observed_at: datetime,
    start_sequence: int = 0,
) -> list[AgentStatement]:
    """Return the statements the agent made, in transcript order.

    `transcript` is the Vogent shape: a list of `{"text": ..., "speaker": "AI"|"HUMAN"}`.
    Only AI segments are considered; what the caller said is not a statement by the agent.
    """
    statements: list[AgentStatement] = []
    sequence = start_sequence

    for index, segment in enumerate(transcript):
        if str(segment.get("speaker", "")).upper() != AI_SPEAKER:
            continue
        text = normalise(str(segment.get("text") or ""))
        if not text.strip():
            continue

        for sentence in (m.group(0).strip() for m in _SENTENCE.finditer(text)):
            if not sentence:
                continue
            disclosed_topics: set[Topic] = set()

            for rule in DISCLOSURE_RULES:
                if rule.pattern.search(sentence):
                    disclosed_topics.add(rule.topic)
                    statements.append(
                        AgentStatement(
                            id=f"stmt-{index}-{sequence}",
                            kind=rule.kind,
                            source=StatementSource.TRANSCRIPT_RULE,
                            observed_at=observed_at,
                            sequence_no=sequence,
                            evidence_text=sentence,
                        )
                    )
                    sequence += 1

            for rule in PROMISE_RULES:
                # A sentence that admits a failure is not also a promise about it.
                if rule.topic in disclosed_topics:
                    continue
                if rule.excludes is not None and rule.excludes.search(sentence):
                    continue
                if rule.pattern.search(sentence):
                    statements.append(
                        AgentStatement(
                            id=f"stmt-{index}-{sequence}",
                            kind=rule.kind,
                            source=StatementSource.TRANSCRIPT_RULE,
                            observed_at=observed_at,
                            sequence_no=sequence,
                            evidence_text=sentence,
                        )
                    )
                    sequence += 1

    return statements
