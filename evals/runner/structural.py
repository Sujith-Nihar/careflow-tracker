"""Cheap structural checks on an exported flow.

These run in milliseconds against `vogent/export/*.json` and cost nothing. They
cannot tell you whether an agent works, but they can tell you whether a flow is
*capable* of telling the truth: whether every line the agent speaks about an
outcome sits downstream of the function that produced it and actually reads its
result.

They are deliberately written against the design as built, not the design as
originally planned. Outcome-conditioned edges on function nodes do not work on
this platform (INVESTIGATIONS.md INV-4), so "counts conditional edges" would be
the wrong rule and would fail a correct flow.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parents[2] / "vogent" / "export"

#: Words that assert an outcome to the caller. A node containing one of these is
#: making a claim, and a claim must be backed by a result it can see.
CLAIM_WORDS = re.compile(
    r"\b(connected|transferred|booked|scheduled|call (you|them) back|all set|"
    r"take it from here|appointment is)\b",
    re.IGNORECASE,
)

TEMPLATE = re.compile(r"\{\{node\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}\}")


@dataclass
class Finding:
    rule: str
    node: str
    detail: str


@dataclass
class StructuralReport:
    version: str
    nodes: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "nodes": self.nodes,
            "passed": self.passed,
            "findings": [
                {"rule": f.rule, "node": f.node, "detail": f.detail}
                for f in self.findings
            ],
        }


def load_flow(version: str) -> dict:
    data = json.loads((EXPORT_DIR / f"{version}.json").read_text())
    return data.get("flowDefinition") or data


def check(version: str) -> StructuralReport:
    flow = load_flow(version)
    nodes = {n["id"]: n for n in flow.get("nodes") or []}
    report = StructuralReport(version=version, nodes=len(nodes))

    functions = {nid: n for nid, n in nodes.items() if n.get("type") == "function"}
    reachable_from = {nid: _downstream(nodes, nid) for nid in nodes}

    for nid, node in nodes.items():
        if node.get("type") != "freeform":
            continue
        prompt = (node.get("nodeData") or {}).get("prompt") or ""
        if not CLAIM_WORDS.search(prompt):
            continue

        # Rule 1: a node that asserts an outcome must read a function result.
        referenced = {m.group(1) for m in TEMPLATE.finditer(prompt)}
        if not referenced & set(functions):
            report.findings.append(
                Finding(
                    "claims_without_reading_a_result",
                    nid,
                    "asserts an outcome to the caller but never reads a function result",
                )
            )
            continue

        # Rule 2: it must actually be downstream of the function it cites.
        for source in referenced & set(functions):
            if nid not in reachable_from.get(source, set()):
                report.findings.append(
                    Finding(
                        "claims_a_result_it_cannot_have",
                        nid,
                        f"reads {source} but is not downstream of it",
                    )
                )

    # Rule 3: the escalation path must exist. Every transfer must be followed by a
    # callback request, because the backend decides whether one is warranted.
    for nid, node in functions.items():
        if "transfer" not in nid:
            continue
        downstream = reachable_from.get(nid, set())
        if not any(
            "callback" in other and nodes[other].get("type") == "function"
            for other in downstream
        ):
            report.findings.append(
                Finding(
                    "transfer_with_no_fallback_path",
                    nid,
                    "no callback function is reachable after a transfer attempt",
                )
            )

    return report


def _downstream(nodes: dict, start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        for rule in nodes.get(current, {}).get("transitionRules") or []:
            target = rule.get("transitionNodeId")
            if target and target not in seen:
                seen.add(target)
                stack.append(target)
    return seen
