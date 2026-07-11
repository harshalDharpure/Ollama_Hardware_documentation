"""Merge text-derived and diagram-derived knowledge graphs."""

from __future__ import annotations

from src.graph.schema import add_node_if_missing, sanitize_id
from src.models import DiagramResult, HDAEdge, HDANode, KnowledgeGraph


def merge_diagram_results(kg: KnowledgeGraph, diagram_results: list[DiagramResult]) -> KnowledgeGraph:
    for dr in diagram_results:
        for node_id in dr.nodes_added:
            nid = sanitize_id(node_id)
            add_node_if_missing(
                kg,
                HDANode(
                    id=nid,
                    type="component",
                    label=node_id,
                    source=dr.figure_id,
                    properties={"pipeline": dr.pipeline_used},
                ),
            )
        for edge in dr.edges_added:
            if not _edge_exists(kg, edge):
                kg.edges.append(edge)

        # Parse mermaid for additional connectivity when edges not pre-built
        if dr.mermaid_code and not dr.edges_added:
            parsed_edges, parsed_nodes = _parse_mermaid(dr.mermaid_code, dr.figure_id)
            for n in parsed_nodes:
                add_node_if_missing(kg, n)
            for e in parsed_edges:
                if not _edge_exists(kg, e):
                    kg.edges.append(e)

    kg.metadata["diagram_count"] = len(diagram_results)
    return kg


def _edge_exists(kg: KnowledgeGraph, edge: HDAEdge) -> bool:
    return any(
        e.from_node == edge.from_node and e.to_node == edge.to_node and e.type == edge.type
        for e in kg.edges
    )


def _parse_mermaid(code: str, source: str) -> tuple[list[HDAEdge], list[HDANode]]:
    import re

    edges: list[HDAEdge] = []
    nodes: list[HDANode] = []
    seen_nodes: set[str] = set()

    for line in code.splitlines():
        line = line.strip()
        if not line or line.startswith(("graph", "flowchart", "%%", "classDef", "style", "subgraph", "end")):
            continue

        # A --> B or A --- B or A -->|label| B
        m = re.match(r"(\w+)\s*[-=.]+(?:\|[^|]+\|)?\s*(\w+)", line)
        if m:
            a, b = sanitize_id(m.group(1)), sanitize_id(m.group(2))
            for nid, label in [(a, m.group(1)), (b, m.group(2))]:
                if nid not in seen_nodes:
                    seen_nodes.add(nid)
                    nodes.append(HDANode(id=nid, type="component", label=label, source=source))
            edges.append(HDAEdge(**{"from": a, "to": b, "type": "CONNECTS", "label": source}))

    return edges, nodes
