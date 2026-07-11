"""Build HDA knowledge graph from implementation plan."""

from __future__ import annotations

import re

from src.graph.schema import add_node_if_missing, sanitize_id
from src.models import HDAEdge, HDANode, ImplementationPlan, KnowledgeGraph, PortDef


def build_kg_from_plan(plan: ImplementationPlan) -> KnowledgeGraph:
    kg = KnowledgeGraph(title=plan.target_function)
    top_id = sanitize_id(plan.target_function or "TopDesign")
    top_node = HDANode(
        id=top_id,
        type="module",
        label=plan.target_function or "Top Design",
        description="Top-level hardware design",
    )
    kg.nodes.append(top_node)

    for module in plan.modules:
        mod_id = sanitize_id(module.name)
        ports: list[PortDef] = []
        for inp in module.inputs:
            ports.append(PortDef(name=_port_name(inp), width=_port_width(inp), direction="in"))
        for out in module.outputs:
            ports.append(PortDef(name=_port_name(out), width=_port_width(out), direction="out"))

        node = HDANode(
            id=mod_id,
            type="module",
            label=module.name,
            description=module.description,
            ports=ports,
            spec_ref=", ".join(module.references),
            properties={
                "functionality": module.functionality,
                "constraints": module.constraints,
                "steps": module.steps,
                "valid": module.valid,
            },
        )
        add_node_if_missing(kg, node)
        kg.edges.append(HDAEdge(**{"from": top_id, "to": mod_id, "type": "CONTAINS"}))

        for dep in module.dependencies:
            dep_id = sanitize_id(dep)
            add_node_if_missing(
                kg,
                HDANode(id=dep_id, type="module", label=dep, description="Dependency module"),
            )
            kg.edges.append(HDAEdge(**{"from": mod_id, "to": dep_id, "type": "DEPENDS_ON"}))

    # Infer CONNECTS from output->input name overlap
    _infer_signal_connections(kg)
    return kg


def _port_name(spec: str) -> str:
    m = re.match(r"([a-zA-Z_][\w]*)", spec.strip())
    return m.group(1) if m else spec.split()[0]


def _port_width(spec: str) -> str:
    m = re.search(r"\[(\d+)[:\s]*0\]|(\d+)-bit", spec, re.IGNORECASE)
    if m:
        return m.group(1) or m.group(2) or ""
    m = re.search(r"(\d+)\s*bit", spec, re.IGNORECASE)
    return m.group(1) if m else ""


def _infer_signal_connections(kg: KnowledgeGraph) -> None:
    modules = [n for n in kg.nodes if n.type == "module" and n.ports]
    for src in modules:
        out_ports = [p for p in src.ports if p.direction == "out"]
        for dst in modules:
            if src.id == dst.id:
                continue
            in_ports = [p for p in dst.ports if p.direction == "in"]
            for o in out_ports:
                for i in in_ports:
                    if _signals_match(o.name, i.name):
                        kg.edges.append(
                            HDAEdge(
                                **{
                                    "from": f"{src.id}.{o.name}",
                                    "to": f"{dst.id}.{i.name}",
                                    "type": "CONNECTS",
                                    "label": o.name,
                                }
                            )
                        )


def _signals_match(a: str, b: str) -> bool:
    a_l, b_l = a.lower(), b.lower()
    if a_l == b_l:
        return True
    for suffix in ("_out", "_in", "_data", "_valid"):
        if a_l.replace(suffix, "") == b_l.replace(suffix, ""):
            return True
    return False
