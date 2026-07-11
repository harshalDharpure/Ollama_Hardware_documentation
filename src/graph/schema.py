"""HDA knowledge graph schema utilities."""

from __future__ import annotations

import re

from src.models import HDAEdge, HDANode, KnowledgeGraph


def sanitize_id(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    if s and s[0].isdigit():
        s = "M_" + s
    return s or "Node"


def validate_graph(kg: KnowledgeGraph) -> list[str]:
    issues: list[str] = []
    node_ids = {n.id for n in kg.nodes}
    for edge in kg.edges:
        if edge.from_node not in node_ids:
            issues.append(f"Edge source missing node: {edge.from_node}")
        if edge.to_node not in node_ids:
            issues.append(f"Edge target missing node: {edge.to_node}")
    return issues


def add_node_if_missing(kg: KnowledgeGraph, node: HDANode) -> None:
    if not any(n.id == node.id for n in kg.nodes):
        kg.nodes.append(node)
