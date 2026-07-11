"""Mermaid diagram generators from HDA knowledge graph."""

from __future__ import annotations

import networkx as nx

from src.models import KnowledgeGraph


def _safe_id(node_id: str) -> str:
    return node_id.replace(".", "_").replace("-", "_").replace(" ", "_")


def build_architecture_mermaid(kg: KnowledgeGraph) -> str:
    lines = ["graph TB"]
    hierarchy = [e for e in kg.edges if e.type in ("CONTAINS", "INSTANCE_OF")]
    if not hierarchy:
        modules = [n for n in kg.nodes if n.type == "module"]
        if modules:
            top = modules[0].id
            lines.append(f"    {_safe_id(top)}[\"{modules[0].label or top}\"]")
            for m in modules[1:]:
                lines.append(f"    {_safe_id(m.id)}[\"{m.label or m.id}\"]")
                lines.append(f"    {_safe_id(top)} --> {_safe_id(m.id)}")
        else:
            lines.append('    Empty["No architecture hierarchy extracted"]')
        return "\n".join(lines)

    seen: set[str] = set()
    for edge in hierarchy:
        fid, tid = _safe_id(edge.from_node), _safe_id(edge.to_node)
        for nid, orig in [(fid, edge.from_node), (tid, edge.to_node)]:
            if nid not in seen:
                label = next((n.label or n.id for n in kg.nodes if n.id == orig), orig)
                lines.append(f"    {nid}[\"{label}\"]")
                seen.add(nid)
        lines.append(f"    {fid} --> {tid}")

    return "\n".join(lines)


def build_dataflow_mermaid(kg: KnowledgeGraph) -> str:
    lines = ["flowchart LR"]
    connects = [e for e in kg.edges if e.type == "CONNECTS"]
    if not connects:
        lines.append('    NoData["No signal-level connections inferred"]')
        return "\n".join(lines)

    seen: set[str] = set()
    for edge in connects:
        fid = _safe_id(edge.from_node.split(".")[0] if "." in edge.from_node else edge.from_node)
        tid = _safe_id(edge.to_node.split(".")[0] if "." in edge.to_node else edge.to_node)
        for nid in (fid, tid):
            if nid not in seen:
                lines.append(f"    {nid}[\"{nid}\"]")
                seen.add(nid)
        label = edge.label or "data"
        lines.append(f"    {fid} -->|{label}| {tid}")

    return "\n".join(lines)


def build_dependency_mermaid(kg: KnowledgeGraph) -> str:
    lines = ["graph TD"]
    deps = [e for e in kg.edges if e.type == "DEPENDS_ON"]
    if not deps:
        modules = [n.id for n in kg.nodes if n.type == "module"]
        if len(modules) > 1:
            for i in range(len(modules) - 1):
                lines.append(f"    {_safe_id(modules[i])} --> {_safe_id(modules[i + 1])}")
        else:
            lines.append('    Solo["Single module — no dependencies"]')
        return "\n".join(lines)

    g = nx.DiGraph()
    for edge in deps:
        g.add_edge(edge.from_node, edge.to_node)

    try:
        order = list(nx.topological_sort(g))
    except nx.NetworkXUnfeasible:
        order = list(g.nodes())

    seen: set[str] = set()
    for node in order:
        nid = _safe_id(node)
        if nid not in seen:
            lines.append(f"    {nid}[\"{node}\"]")
            seen.add(nid)

    for edge in deps:
        lines.append(f"    {_safe_id(edge.from_node)} --> {_safe_id(edge.to_node)}")

    return "\n".join(lines)


def combine_diagram_mermaids(diagram_results: list, title: str = "Combined Diagrams") -> str:
    """Merge per-figure Mermaid into one diagram with subgraphs per source."""
    lines = ["graph TB"]
    if not diagram_results:
        lines.append('    Empty["No diagram Mermaid generated"]')
        return "\n".join(lines)

    added = False
    for dr in diagram_results:
        if not dr.mermaid_code or "Error" in dr.mermaid_code:
            continue
        sub_id = _safe_id(dr.figure_id)
        lines.append(f"    subgraph {sub_id}[\"{dr.figure_id}\"]")
        for mline in dr.mermaid_code.splitlines():
            mline = mline.strip()
            if not mline or mline.startswith(("graph", "flowchart", "%%", "subgraph")) or mline == "end":
                continue
            lines.append(f"        {mline}")
            added = True
        lines.append("    end")

    if not added:
        lines.append(f'    Info["{title}: see individual diagram tabs"]')
    return "\n".join(lines)
