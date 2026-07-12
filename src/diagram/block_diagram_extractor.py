"""Semantic block-diagram extraction without J-label leakage."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.llm.ollama_client import OllamaClient
from src.models import (
    BlockComponent,
    BlockDiagramEvidence,
    BlockDiagramWarning,
    BlockRelationship,
    DiagramType,
    ExternalSignal,
    ExtractedFigure,
)

BLOCK_EXTRACT_SYSTEM = """You are a hardware datasheet analyst. Extract semantic block-diagram
information from images. Use real component and signal names from the diagram. Never output
intermediate detection labels like J1, J2, C1, or C2. Respond ONLY with valid JSON."""

BLOCK_EXTRACT_PROMPT = """Analyze this hardware block diagram page and extract structured evidence.

Return JSON:
{{
  "components": [
    {{"id": "power_control", "name": "Power Control", "type": "power"}}
  ],
  "external_signals": [
    {{"name": "VCC", "direction": "input", "function": "primary supply"}}
  ],
  "relationships": [
    {{
      "source": "VCC",
      "target": "power_control",
      "relationship": "powers",
      "evidence": "input arrow in block diagram",
      "confidence": "high"
    }}
  ],
  "warnings": [
    {{
      "type": "ambiguous_arrow_direction",
      "relationship": "temperature_sensor_to_i2c",
      "action": "manual verification recommended"
    }}
  ],
  "confidence": 0.9
}}

Rules:
- Use semantic names only (Power Control, I2C Interface, Clock and Calendar Registers)
- Include arrow direction semantics in relationship names (powers, reads_writes, provides_1hz_tick)
- Do not invent blocks not visible in the diagram
- Flag ambiguous connections in warnings"""


def is_block_diagram_page(figure: ExtractedFigure, diagram_type: DiagramType) -> bool:
    if diagram_type == DiagramType.BLOCK_DIAGRAM:
        return True
    caption = (figure.caption or "").lower()
    section = (figure.section_ref or "").lower()
    return any(k in caption + section for k in ("block", "functional", "architecture"))


def extract_block_diagram(
    client: OllamaClient,
    figure: ExtractedFigure,
    diagram_type: DiagramType,
    force: bool = False,
) -> BlockDiagramEvidence | None:
    if not force and not is_block_diagram_page(figure, diagram_type):
        return None

    path = Path(figure.path)
    if not path.exists():
        return None

    try:
        raw = client.chat_vision(BLOCK_EXTRACT_PROMPT, path, system=BLOCK_EXTRACT_SYSTEM)
        data = _parse_evidence_json(raw)
    except Exception:
        return None

    page = figure.page or 0
    components = [
        BlockComponent(
            id=_slug(c.get("id") or c.get("name", "")),
            name=str(c.get("name", "")),
            type=str(c.get("type", "block")),
        )
        for c in data.get("components", [])
        if c.get("name")
    ]
    external_signals = [
        ExternalSignal(
            name=str(s.get("name", "")),
            direction=str(s.get("direction", "")),
            function=str(s.get("function", "")),
        )
        for s in data.get("external_signals", [])
        if s.get("name")
    ]
    relationships = [
        BlockRelationship(
            source=str(r.get("source", "")),
            target=str(r.get("target", "")),
            relationship=str(r.get("relationship", r.get("relation", ""))),
            evidence=str(r.get("evidence", "")),
            confidence=str(r.get("confidence", "medium")),
            source_pdf_page=int(r.get("source_pdf_page", page) or page),
        )
        for r in data.get("relationships", [])
        if r.get("source") and r.get("target")
    ]
    warnings = [
        BlockDiagramWarning(
            type=str(w.get("type", "")),
            relationship=str(w.get("relationship", "")),
            action=str(w.get("action", "")),
        )
        for w in data.get("warnings", [])
    ]

    return BlockDiagramEvidence(
        page=page,
        figure_id=figure.id,
        components=components,
        external_signals=external_signals,
        relationships=relationships,
        warnings=warnings,
        confidence=float(data.get("confidence", 0.7)),
    )


def merge_block_evidence(evidence_list: list[BlockDiagramEvidence]) -> BlockDiagramEvidence:
    if not evidence_list:
        return BlockDiagramEvidence()

    merged = BlockDiagramEvidence(
        page=evidence_list[0].page,
        figure_id="merged_block_diagram",
    )
    seen_components: set[str] = set()
    seen_relationships: set[str] = set()

    for ev in evidence_list:
        for comp in ev.components:
            if comp.id not in seen_components:
                merged.components.append(comp)
                seen_components.add(comp.id)
        for sig in ev.external_signals:
            if sig.name and sig.name not in {s.name for s in merged.external_signals}:
                merged.external_signals.append(sig)
        for rel in ev.relationships:
            key = f"{rel.source}|{rel.relationship}|{rel.target}"
            if key not in seen_relationships:
                merged.relationships.append(rel)
                seen_relationships.add(key)
        merged.warnings.extend(ev.warnings)
        merged.confidence = max(merged.confidence, ev.confidence)

    return merged


def evidence_to_json(evidence: BlockDiagramEvidence) -> str:
    return json.dumps(evidence.model_dump(), indent=2)


def _parse_evidence_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
        raise


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w]+", "_", value).strip("_")
    return value or "block"
