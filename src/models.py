"""Shared data models for the spec conversion pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DiagramType(str, Enum):
    BLOCK_DIAGRAM = "block_diagram"
    SCHEMATIC = "schematic"
    TABLE = "table"
    OTHER = "other"
    DENSE_COMPLEX = "dense_complex"


class SectionChunk(BaseModel):
    id: str
    title: str
    level: int = 1
    content: str
    page_start: int | None = None
    page_end: int | None = None
    figure_refs: list[str] = Field(default_factory=list)


class ExtractedFigure(BaseModel):
    id: str
    path: str
    page: int | None = None
    caption: str = ""
    section_ref: str = ""
    width: int = 0
    height: int = 0
    source_type: str = "embedded"  # embedded | page_render


class ExtractedTable(BaseModel):
    id: str
    page: int
    markdown: str = ""
    rows: list[list[str]] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    caption: str = ""


class PageRecord(BaseModel):
    page_num: int
    text: str = ""
    char_count: int = 0
    table_count: int = 0
    figure_count: int = 0
    is_diagram_page: bool = False
    render_path: str = ""


class DocumentBundle(BaseModel):
    source_path: str
    format: str
    title: str = "Untitled Specification"
    sections: list[SectionChunk] = Field(default_factory=list)
    figures: list[ExtractedFigure] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    pages: list[PageRecord] = Field(default_factory=list)
    raw_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SectionSummary(BaseModel):
    section_id: str
    title: str
    purpose: str = ""
    key_concepts: list[str] = Field(default_factory=list)
    figure_refs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ModuleSpec(BaseModel):
    name: str
    description: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    functionality: str = ""
    constraints: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    order: int = 0
    dependencies: list[str] = Field(default_factory=list)
    valid: bool = False
    audit_issues: list[str] = Field(default_factory=list)


class ImplementationPlan(BaseModel):
    target_function: str = ""
    modules: list[ModuleSpec] = Field(default_factory=list)
    section_summaries: list[SectionSummary] = Field(default_factory=list)


class PortDef(BaseModel):
    name: str
    width: str = ""
    direction: str = "in"


class HDANode(BaseModel):
    id: str
    type: str = "module"  # module | component | pin | signal
    label: str = ""
    description: str = ""
    ports: list[PortDef] = Field(default_factory=list)
    spec_ref: str = ""
    source: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class HDAEdge(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    type: str = "CONNECTS"  # CONTAINS | DEPENDS_ON | CONNECTS | INSTANCE_OF
    label: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class KnowledgeGraph(BaseModel):
    title: str = ""
    nodes: list[HDANode] = Field(default_factory=list)
    edges: list[HDAEdge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiagramResult(BaseModel):
    figure_id: str
    diagram_type: DiagramType
    original_path: str
    labeled_path: str = ""
    mermaid_code: str = ""
    nodes_added: list[str] = Field(default_factory=list)
    edges_added: list[HDAEdge] = Field(default_factory=list)
    pipeline_used: str = "nsc"
    confidence: float = 0.0


class QualityReport(BaseModel):
    completeness_score: float = 0.0
    section_coverage: float = 0.0
    modules_valid: int = 0
    modules_total: int = 0
    diagram_fidelity: float = 0.0
    pages_processed: int = 0
    tables_extracted: int = 0
    figures_extracted: int = 0
    diagrams_generated: int = 0
    conflicts: list[str] = Field(default_factory=list)


class PipelineResult(BaseModel):
    document: DocumentBundle
    plan: ImplementationPlan
    knowledge_graph: KnowledgeGraph
    markdown: str = ""
    architecture_mermaid: str = ""
    dataflow_mermaid: str = ""
    dependency_mermaid: str = ""
    combined_diagram_mermaid: str = ""
    diagram_results: list[DiagramResult] = Field(default_factory=list)
    quality: QualityReport = Field(default_factory=QualityReport)
    export_dir: str = ""
