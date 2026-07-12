"""Unified datasheet synthesizer producing hackathon deliverables."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from src.llm.ollama_client import OllamaClient
from src.models import (
    BlockDiagramEvidence,
    DocumentBundle,
    ImplementationPlan,
    NormalizedParameterRow,
    QualityReport,
    SectionSummary,
    SpatialNetlist,
)
from src.output.mermaid_sanitizer import cap_mermaid_edges, count_mermaid_edges, is_valid_mermaid, sanitize_mermaid

MAX_SPATIAL_EDGES = 60
MAX_SPATIAL_NETS = 50

SYNTH_SYSTEM = """You are an expert hardware datasheet analyst producing agent-friendly
specification artifacts. Be accurate, cite source PDF pages, flag missing information
instead of inventing values. Never use intermediate diagram labels like J1, J2, C1.
Respond ONLY with valid JSON unless generating Mermaid inside JSON fields."""

SPEC_PROMPT = """Create a professional hardware specification markdown document.

Device: {title}
Pages: {page_count}
Source file: {source_file}

Section summaries:
{summaries}

Normalized electrical parameters:
{parameters}

Block diagram evidence:
{block_evidence}

Specification text:
{text}

Return JSON:
{{
  "specification_markdown": "full markdown with numbered sections 1-6+",
  "warnings": ["string warnings about missing pages or ambiguous data"],
  "sections_detected": ["section names"],
  "functional_blocks": [
    {{"name": "Oscillator and Capacitor Array", "purpose": "...", "source_pdf_page": 8}}
  ]
}}

Requirements:
- Section 1: Document Information table
- Section 2: Functional Overview (bullet list of blocks)
- Section 3: External Interfaces table
- Section 4+: Electrical Characteristics from normalized parameters
- Section 6: Functional Blocks with purpose paragraphs
- Engineer-readable prose, not OCR dump
- No J1/J2/C1 labels"""

CANONICAL_PROMPT = """Build canonical JSON for AI agents from datasheet evidence.

Device: {title}
Pages: {page_count}

Normalized parameters:
{parameters}

Block diagram evidence:
{block_evidence}

Interfaces from evidence:
{interfaces}

Text excerpt:
{text}

Return JSON:
{{
  "document": {{
    "device": "",
    "manufacturer": "",
    "device_type": "",
    "source_file": "",
    "source_pages": []
  }},
  "interfaces": [
    {{"name": "SCL", "direction": "input", "protocol": "I2C", "function": "serial clock"}}
  ],
  "components": [
    {{"id": "oscillator", "name": "Oscillator and Capacitor Array", "type": "clock_generation"}}
  ],
  "relationships": [
    {{"source": "oscillator", "target": "divider", "relationship": "provides_clock"}}
  ],
  "electrical_characteristics": [
    {{
      "parameter": "Output Frequency",
      "symbol": "fOUT",
      "conditions": {{"supply": "VCC = 3.3 V"}},
      "typical": 32.768,
      "unit": "kHz",
      "source": {{"page": 3, "section": "Electrical Characteristics"}}
    }}
  ],
  "functional_blocks": [
    {{"id": "oscillator", "name": "Oscillator and Capacitor Array", "purpose": "..."}}
  ],
  "normalization": {{"uA": ["µA", "microampere"]}}
}}"""

MERMAID_ARCH_PROMPT = """Generate architecture Mermaid from block diagram evidence.

Device: {title}
Block evidence JSON:
{block_evidence}

Style example (structure only, use actual device blocks):
flowchart LR
    subgraph External["External Signals"]
        VCC["VCC"]
    end
    subgraph CHIP["Device"]
        POWER["Power Control"]
    end
    VCC --> POWER

Rules: flowchart LR, semantic labels in double quotes, no J1/J2/C1, no markdown fences.
Return JSON: {{"mermaid": "..."}}"""

MERMAID_FLOW_PROMPT = """Generate data-flow Mermaid from block diagram evidence and interfaces.

Device: {title}
Block evidence:
{block_evidence}
Parameters context:
{parameters}

Rules: flowchart LR, show register/bus/data paths, semantic names only.
Return JSON: {{"mermaid": "..."}}"""

MERMAID_DEP_PROMPT = """Generate dependency graph Mermaid from block diagram evidence.

Device: {title}
Block evidence:
{block_evidence}

Rules: graph TD, show power/clock/control dependencies between blocks.
Return JSON: {{"mermaid": "..."}}"""


def synthesize_datasheet_deliverables(
    client: OllamaClient,
    document: DocumentBundle,
    summaries: list[SectionSummary],
    block_evidence: BlockDiagramEvidence,
    normalized_parameters: list[NormalizedParameterRow],
    quality: QualityReport,
    title: str | None = None,
    spatial_netlist: SpatialNetlist | None = None,
) -> dict[str, Any]:
    device_title = title or document.title
    page_count = len(document.pages)
    source_file = Path(document.source_path).name

    summaries_json = json.dumps([s.model_dump() for s in summaries[:25]], indent=2)
    params_json = json.dumps([p.model_dump() for p in normalized_parameters[:80]], indent=2)
    block_json = json.dumps(block_evidence.model_dump(), indent=2)
    text = document.raw_text[:16000]
    interfaces = json.dumps([s.model_dump() for s in block_evidence.external_signals], indent=2)

    spec_data = _llm_json(
        client,
        SPEC_PROMPT.format(
            title=device_title,
            page_count=page_count,
            source_file=source_file,
            summaries=summaries_json,
            parameters=params_json,
            block_evidence=block_json,
            text=text,
        ),
        _fallback_specification(document, device_title, normalized_parameters, block_evidence),
    )

    canonical = _llm_json(
        client,
        CANONICAL_PROMPT.format(
            title=device_title,
            page_count=page_count,
            parameters=params_json,
            block_evidence=block_json,
            interfaces=interfaces,
            text=text,
        ),
        _fallback_canonical(document, device_title, normalized_parameters, block_evidence),
    )

    arch_mmd = _build_mermaid(
        client, MERMAID_ARCH_PROMPT, device_title, block_json, params_json, "architecture", block_evidence
    )
    flow_mmd = _build_mermaid(
        client, MERMAID_FLOW_PROMPT, device_title, block_json, params_json, "dataflow", block_evidence
    )
    dep_mmd = _build_mermaid(
        client, MERMAID_DEP_PROMPT, device_title, block_json, params_json, "dependency", block_evidence
    )

    if spatial_netlist and spatial_netlist.symbols:
        spatial_arch = _usable_spatial_mermaid(spatial_netlist, "architecture")
        spatial_flow = _usable_spatial_mermaid(spatial_netlist, "dataflow")
        spatial_dep = _usable_spatial_mermaid(spatial_netlist, "dependency")
        if spatial_arch:
            arch_mmd = spatial_arch
        if spatial_flow:
            flow_mmd = spatial_flow
        if spatial_dep:
            dep_mmd = spatial_dep

    spec_md = spec_data.get("specification_markdown", "")
    if spec_md and "```mermaid" not in spec_md:
        spec_md = _append_mermaid_sections(spec_md, arch_mmd, flow_mmd, dep_mmd)

    relationships_csv = _relationships_to_csv(canonical, block_evidence)
    electrical_csv = _electrical_to_csv(canonical, normalized_parameters)
    extraction_report = _build_extraction_report(
        document=document,
        title=device_title,
        spec_data=spec_data,
        canonical=canonical,
        block_evidence=block_evidence,
        quality=quality,
        arch_mmd=arch_mmd,
        flow_mmd=flow_mmd,
        dep_mmd=dep_mmd,
        spatial_netlist=spatial_netlist,
    )

    return {
        "specification": spec_md,
        "structured_specification": spec_md,
        "canonical_spec": canonical,
        "architecture_mermaid": arch_mmd,
        "dataflow_mermaid": flow_mmd,
        "dependency_mermaid": dep_mmd,
        "relationships_csv": relationships_csv,
        "electrical_characteristics_csv": electrical_csv,
        "extraction_report": extraction_report,
    }


def _usable_spatial_mermaid(netlist: SpatialNetlist, kind: str) -> str | None:
    """Use spatial-netlist Mermaid only when it is valid and not overly dense."""
    attr = {
        "architecture": "mermaid_architecture",
        "dataflow": "mermaid_dataflow",
        "dependency": "mermaid_dependency",
    }.get(kind)
    if not attr:
        return None
    mmd = getattr(netlist, attr, "") or ""
    if not mmd or "Empty" in mmd or "Unavailable" in mmd:
        return None
    if len(netlist.nets) > MAX_SPATIAL_NETS:
        return None
    if not is_valid_mermaid(mmd):
        return None
    if count_mermaid_edges(mmd) > MAX_SPATIAL_EDGES:
        return None
    return cap_mermaid_edges(sanitize_mermaid(mmd), MAX_SPATIAL_EDGES)


def _llm_json(client: OllamaClient, prompt: str, fallback: dict) -> dict:
    try:
        raw = client.chat_text(prompt, system=SYNTH_SYSTEM, json_mode=True)
        return client.parse_json_response(raw)
    except Exception:
        return fallback


def _build_mermaid(
    client: OllamaClient,
    template: str,
    title: str,
    block_json: str,
    params_json: str,
    kind: str,
    block_evidence: BlockDiagramEvidence,
) -> str:
    prompt = template.format(
        title=title,
        block_evidence=block_json,
        parameters=params_json,
    )
    try:
        raw = client.chat_text(prompt, system=SYNTH_SYSTEM, json_mode=True)
        code = _extract_mermaid_code(raw, client)
        if code and "J1" not in code and "J2" not in code and is_valid_mermaid(code):
            return sanitize_mermaid(code)
    except Exception:
        pass

    evidence_mmd = _mermaid_from_evidence(block_evidence, kind)
    if evidence_mmd:
        return sanitize_mermaid(evidence_mmd)
    return _skeleton_mermaid(kind)


def _extract_mermaid_code(raw: str, client: OllamaClient) -> str:
    try:
        data = client.parse_json_response(raw)
        code = str(data.get("mermaid", "")).strip()
        if code:
            return code
    except Exception:
        pass

    text = raw.strip()
    if "```" in text:
        match = re.search(r"```(?:mermaid)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    for starter in ("flowchart LR", "flowchart TB", "flowchart TD", "graph TD", "graph LR", "graph TB"):
        idx = text.find(starter)
        if idx >= 0:
            return text[idx:].strip()
    return ""


def _safe_node_id(name: str) -> str:
    safe = re.sub(r"[^\w]", "_", name.strip()).strip("_") or "Node"
    if safe[0].isdigit():
        safe = f"N_{safe}"
    return safe


def _quote_label(label: str) -> str:
    return label.replace('"', "'")


def _resolve_node_id(name: str, evidence: BlockDiagramEvidence) -> str:
    for comp in evidence.components:
        if name in {comp.id, comp.name}:
            return _safe_node_id(comp.id or comp.name)
    for sig in evidence.external_signals:
        if name == sig.name:
            return _safe_node_id(sig.name)
    return _safe_node_id(name)


def _mermaid_from_evidence(evidence: BlockDiagramEvidence, kind: str) -> str:
    if not evidence.components and not evidence.relationships and not evidence.external_signals:
        return ""

    if kind == "dependency":
        return _dependency_mermaid_from_evidence(evidence)
    if kind == "dataflow":
        return _dataflow_mermaid_from_evidence(evidence)
    if kind == "architecture":
        return _architecture_mermaid_from_evidence(evidence)
    return ""


def _architecture_mermaid_from_evidence(evidence: BlockDiagramEvidence) -> str:
    lines = ["flowchart LR"]
    if evidence.external_signals:
        lines.append('    subgraph External["External Signals"]')
        for sig in evidence.external_signals:
            nid = _safe_node_id(sig.name)
            lines.append(f'        {nid}["{_quote_label(sig.name)}"]')
        lines.append("    end")

    if evidence.components:
        lines.append('    subgraph CHIP["Device"]')
        for comp in evidence.components:
            nid = _safe_node_id(comp.id or comp.name)
            lines.append(f'        {nid}["{_quote_label(comp.name)}"]')
        lines.append("    end")

    for rel in evidence.relationships:
        src = _resolve_node_id(rel.source, evidence)
        dst = _resolve_node_id(rel.target, evidence)
        label = _quote_label(rel.relationship or "connects")
        lines.append(f'    {src} -->|"{label}"| {dst}')

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _dependency_mermaid_from_evidence(evidence: BlockDiagramEvidence) -> str:
    lines = ["graph TD"]
    declared: set[str] = set()

    def declare(name: str) -> str:
        nid = _resolve_node_id(name, evidence)
        if nid not in declared:
            lines.append(f'    {nid}["{_quote_label(name)}"]')
            declared.add(nid)
        return nid

    for comp in evidence.components:
        declare(comp.name)
    for sig in evidence.external_signals:
        declare(sig.name)

    added_edge = False
    for rel in evidence.relationships:
        src = declare(rel.source)
        dst = declare(rel.target)
        lines.append(f"    {src} --> {dst}")
        added_edge = True

    if not added_edge and evidence.components:
        ordered = [_safe_node_id(c.id or c.name) for c in evidence.components]
        for comp, nid in zip(evidence.components, ordered):
            if nid not in declared:
                lines.append(f'    {nid}["{_quote_label(comp.name)}"]')
                declared.add(nid)
        for i in range(len(ordered) - 1):
            lines.append(f"    {ordered[i]} --> {ordered[i + 1]}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _dataflow_mermaid_from_evidence(evidence: BlockDiagramEvidence) -> str:
    lines = ["flowchart LR"]
    declared: set[str] = set()

    def declare(name: str) -> str:
        nid = _resolve_node_id(name, evidence)
        if nid not in declared:
            lines.append(f'    {nid}["{_quote_label(name)}"]')
            declared.add(nid)
        return nid

    bus_like = [s.name for s in evidence.external_signals if s.name.upper() in {"SCL", "SDA", "I2C"}]
    if bus_like:
        bus_id = declare("I2C Bus")
        for sig in evidence.external_signals:
            if sig.name.upper() in {"SCL", "SDA"}:
                declare(sig.name)
                lines.append(f'    {declare(sig.name)} --> {bus_id}')

    for comp in evidence.components:
        declare(comp.name)

    for rel in evidence.relationships:
        rel_name = (rel.relationship or "").lower()
        src = declare(rel.source)
        dst = declare(rel.target)
        if any(token in rel_name for token in ("read", "write", "bus", "data", "register", "i2c")):
            label = _quote_label(rel.relationship or "data")
            lines.append(f'    {src} -->|"{label}"| {dst}')
        else:
            lines.append(f"    {src} --> {dst}")

    if len(declared) <= 1:
        return _architecture_mermaid_from_evidence(evidence)
    return "\n".join(lines)


def _skeleton_mermaid(kind: str) -> str:
    if kind == "dependency":
        return sanitize_mermaid('graph TD\n    Unavailable["Dependency diagram could not be generated"]')
    return sanitize_mermaid('flowchart LR\n    Unavailable["Diagram could not be generated"]')


def _append_mermaid_sections(md: str, arch: str, flow: str, dep: str) -> str:
    lines = [md.rstrip(), ""]
    for idx, (title, code) in enumerate(
        [
            ("Architecture Diagram", arch),
            ("Data Flow Diagram", flow),
            ("Dependency Graph", dep),
        ],
        start=7,
    ):
        lines.extend([f"## {idx}. {title}", "", "```mermaid", code, "```", ""])
    return "\n".join(lines)


def _relationships_to_csv(canonical: dict, block_evidence: BlockDiagramEvidence) -> str:
    rows: list[list[str]] = [
        ["source", "relation", "target", "evidence", "source_pdf_page", "confidence"]
    ]
    for rel in canonical.get("relationships", []):
        rows.append([
            str(rel.get("source", "")),
            str(rel.get("relationship", rel.get("relation", ""))),
            str(rel.get("target", "")),
            str(rel.get("evidence", "")),
            str(rel.get("source_pdf_page", rel.get("source", {}).get("page", "") if isinstance(rel.get("source"), dict) else "")),
            str(rel.get("confidence", "medium")),
        ])
    if len(rows) == 1:
        for rel in block_evidence.relationships:
            rows.append([
                rel.source,
                rel.relationship,
                rel.target,
                rel.evidence,
                str(rel.source_pdf_page),
                rel.confidence,
            ])
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def _electrical_to_csv(
    canonical: dict,
    normalized_parameters: list[NormalizedParameterRow],
) -> str:
    rows: list[list[str]] = [
        [
            "category", "parameter", "symbol", "conditions", "supply",
            "minimum", "typical", "maximum", "unit", "original_unit", "source_pdf_page", "section",
        ]
    ]
    for item in canonical.get("electrical_characteristics", []):
        cond = item.get("conditions", {})
        if isinstance(cond, dict):
            cond_str = "; ".join(f"{k}={v}" for k, v in cond.items())
        else:
            cond_str = str(cond)
        source = item.get("source", {})
        page = source.get("page", "") if isinstance(source, dict) else item.get("source_pdf_page", "")
        rows.append([
            str(item.get("category", "")),
            str(item.get("parameter", "")),
            str(item.get("symbol", "")),
            cond_str,
            str(item.get("supply", "")),
            str(item.get("minimum", "")),
            str(item.get("typical", "")),
            str(item.get("maximum", "")),
            str(item.get("unit", "")),
            str(item.get("original_unit", "")),
            str(page),
            str(source.get("section", "") if isinstance(source, dict) else ""),
        ])
    if len(rows) == 1:
        for p in normalized_parameters:
            rows.append([
                p.category, p.parameter, p.symbol, p.conditions, p.supply,
                p.minimum, p.typical, p.maximum, p.unit, p.original_unit,
                str(p.source_pdf_page), p.section,
            ])
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


def _build_extraction_report(
    document: DocumentBundle,
    title: str,
    spec_data: dict,
    canonical: dict,
    block_evidence: BlockDiagramEvidence,
    quality: QualityReport,
    arch_mmd: str,
    flow_mmd: str,
    dep_mmd: str,
    spatial_netlist: SpatialNetlist | None = None,
) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    for w in spec_data.get("warnings", []):
        if isinstance(w, str):
            warnings.append({"type": "extraction_note", "relationship": "", "action": w})
        elif isinstance(w, dict):
            warnings.append(w)
    for w in block_evidence.warnings:
        warnings.append(w.model_dump())

    mermaid_ok = all(
        "Unavailable" not in m and "Empty" not in m
        for m in (arch_mmd, flow_mmd, dep_mmd)
    )

    return {
        "document_id": title,
        "pages_processed": len(document.pages),
        "tables_detected": len(document.tables),
        "diagram_blocks_detected": len(block_evidence.components),
        "connections_detected": len(block_evidence.relationships),
        "omnish_symbols_detected": len(spatial_netlist.symbols) if spatial_netlist else 0,
        "omnish_text_instances": len(spatial_netlist.texts) if spatial_netlist else 0,
        "omnish_nets_detected": len(spatial_netlist.nets) if spatial_netlist else 0,
        "omnish_pipeline": spatial_netlist.pipeline if spatial_netlist else "",
        "sections_detected": spec_data.get("sections_detected", []),
        "warnings": warnings,
        "confidence": {
            "text_extraction": round(min(0.98, 0.7 + quality.section_coverage * 0.28), 2),
            "table_structure": round(min(0.96, 0.5 + quality.tables_extracted * 0.08), 2),
            "component_detection": round(
                max(block_evidence.confidence, spatial_netlist.confidence if spatial_netlist else 0.0), 2
            ),
            "relationship_detection": round(
                min(0.9, 0.5 + max(len(block_evidence.relationships), len(spatial_netlist.nets) if spatial_netlist else 0) * 0.02),
                2,
            ),
            "diagram_generation": 0.91 if mermaid_ok else 0.5,
            "spatial_netlist": round(spatial_netlist.confidence, 2) if spatial_netlist else 0.0,
        },
        "deliverables": [
            "specification.md",
            "canonical_spec.json",
            "architecture.mmd",
            "data_flow.mmd",
            "dependency_graph.mmd",
            "extraction_report.json",
        ],
    }


def _fallback_specification(
    document: DocumentBundle,
    title: str,
    parameters: list[NormalizedParameterRow],
    block_evidence: BlockDiagramEvidence,
) -> dict[str, Any]:
    lines = [
        f"# {title} Hardware Specification",
        "",
        "## 1. Document Information",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Device | {title} |",
        f"| Uploaded pages | {len(document.pages)} |",
        f"| Source file | {Path(document.source_path).name} |",
        "",
        "## 2. Functional Overview",
        "",
    ]
    for comp in block_evidence.components:
        lines.append(f"- {comp.name}")
    lines.extend(["", "## 3. External Interfaces", "", "| Signal | Direction | Function |", "|---|---|---|"])
    for sig in block_evidence.external_signals:
        lines.append(f"| {sig.name} | {sig.direction} | {sig.function} |")
    if parameters:
        lines.extend(["", "## 4. Electrical Characteristics", "", "| Parameter | Symbol | Min | Typ | Max | Unit | Page |", "|---|---|---:|---:|---:|---|---:|"])
        for p in parameters[:30]:
            lines.append(f"| {p.parameter} | {p.symbol} | {p.minimum} | {p.typical} | {p.maximum} | {p.unit} | {p.source_pdf_page} |")
    return {
        "specification_markdown": "\n".join(lines),
        "warnings": ["LLM synthesis unavailable; template specification generated from extracted evidence"],
        "sections_detected": ["Document Information", "Functional Overview", "External Interfaces"],
        "functional_blocks": [{"name": c.name, "purpose": c.type, "source_pdf_page": block_evidence.page} for c in block_evidence.components],
    }


def _fallback_canonical(
    document: DocumentBundle,
    title: str,
    parameters: list[NormalizedParameterRow],
    block_evidence: BlockDiagramEvidence,
) -> dict[str, Any]:
    return {
        "document": {
            "device": title,
            "source_file": Path(document.source_path).name,
            "source_pages": [p.page_num for p in document.pages],
        },
        "interfaces": [s.model_dump() for s in block_evidence.external_signals],
        "components": [c.model_dump() for c in block_evidence.components],
        "relationships": [r.model_dump() for r in block_evidence.relationships],
        "electrical_characteristics": [
            {
                "parameter": p.parameter,
                "symbol": p.symbol,
                "conditions": {"text": p.conditions},
                "minimum": p.minimum,
                "typical": p.typical,
                "maximum": p.maximum,
                "unit": p.unit,
                "source": {"page": p.source_pdf_page, "section": p.section},
            }
            for p in parameters
        ],
        "functional_blocks": [{"id": c.id, "name": c.name, "purpose": c.type} for c in block_evidence.components],
        "normalization": {"uA": ["µA", "microampere", "uA"]},
    }
