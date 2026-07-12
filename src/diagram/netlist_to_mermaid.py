"""Generate Mermaid diagrams from spatial netlists (no raw LLM text)."""

from __future__ import annotations

import re

from src.models import SpatialNetlist, SymbolInstance
from src.output.mermaid_sanitizer import sanitize_mermaid

MAX_ARCH_EDGES = 25
MAX_FLOW_EDGES = 30
MAX_DEP_EDGES = 25
MAX_COMPONENTS = 18


def _safe_id(name: str) -> str:
    safe = re.sub(r"[^\w]", "_", name.strip()).strip("_") or "Node"
    if safe[0].isdigit():
        safe = f"N_{safe}"
    return safe


def _label(sym: SymbolInstance) -> str:
    return sym.name.replace('"', "'")


def netlist_to_architecture_mermaid(netlist: SpatialNetlist) -> str:
    comps = [s for s in netlist.symbols if s.symbol_type in {"component", "text_anchor"}]
    if not comps:
        return ""

    lines = ["flowchart LR"]
    declared: set[str] = set()

    externals = [s for s in comps if s.symbol_type == "text_anchor" and len(s.name) <= 8]
    internals = [s for s in comps if s not in externals]

    if externals:
        lines.append('    subgraph External["External Signals"]')
        for sym in externals[:8]:
            nid = _safe_id(sym.id)
            lines.append(f'        {nid}["{_label(sym)}"]')
            declared.add(nid)
        lines.append("    end")

    if internals:
        lines.append('    subgraph CHIP["Device"]')
        for sym in internals[:MAX_COMPONENTS]:
            nid = _safe_id(sym.id)
            lines.append(f'        {nid}["{_label(sym)}"]')
            declared.add(nid)
        lines.append("    end")

    for net in netlist.nets[:MAX_ARCH_EDGES]:
        src = _safe_id(net.source_id)
        dst = _safe_id(net.target_id)
        if src not in declared and dst not in declared:
            continue
        rel = net.relationship.replace('"', "'")
        lines.append(f'    {src} -->|"{rel}"| {dst}')

    if len(lines) <= 1:
        return ""
    return sanitize_mermaid("\n".join(lines))


def netlist_to_dataflow_mermaid(netlist: SpatialNetlist) -> str:
    comps = {s.id: s for s in netlist.symbols if s.symbol_type != "junction"}
    if not comps:
        return ""

    lines = ["flowchart LR"]
    declared: set[str] = set()

    def declare(sym_id: str) -> str:
        sym = comps.get(sym_id)
        if not sym:
            return _safe_id(sym_id)
        nid = _safe_id(sym.id)
        if nid not in declared:
            lines.append(f'    {nid}["{_label(sym)}"]')
            declared.add(nid)
        return nid

    for net in netlist.nets[:MAX_FLOW_EDGES]:
        src = declare(net.source_id)
        dst = declare(net.target_id)
        label = (net.net_name or net.relationship or "data").replace('"', "'")
        lines.append(f'    {src} -->|"{label}"| {dst}')

    if len(lines) <= 1:
        return netlist_to_architecture_mermaid(netlist)
    return sanitize_mermaid("\n".join(lines))


def netlist_to_dependency_mermaid(netlist: SpatialNetlist) -> str:
    comps = [s for s in netlist.symbols if s.symbol_type == "component"]
    if not comps:
        return ""

    lines = ["graph TD"]
    for sym in comps[:MAX_COMPONENTS]:
        lines.append(f'    {_safe_id(sym.id)}["{_label(sym)}"]')

    added = False
    for net in netlist.nets[:MAX_DEP_EDGES]:
        if net.spatial_weight < 0.25:
            continue
        lines.append(f"    {_safe_id(net.source_id)} --> {_safe_id(net.target_id)}")
        added = True

    if not added and len(comps) > 1:
        for i in range(len(comps) - 1):
            lines.append(f"    {_safe_id(comps[i].id)} --> {_safe_id(comps[i + 1].id)}")

    if len(lines) <= 1:
        return ""
    return sanitize_mermaid("\n".join(lines))


def enrich_netlist_mermaid(netlist: SpatialNetlist) -> SpatialNetlist:
    netlist.mermaid_architecture = netlist_to_architecture_mermaid(netlist)
    netlist.mermaid_dataflow = netlist_to_dataflow_mermaid(netlist)
    netlist.mermaid_dependency = netlist_to_dependency_mermaid(netlist)
    return netlist
