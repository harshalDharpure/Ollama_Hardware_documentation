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


class BoundingBox(BaseModel):
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)


class TextInstance(BaseModel):
    text: str
    bbox: BoundingBox
    confidence: float = 0.0
    source: str = "ocr"


class SymbolInstance(BaseModel):
    id: str
    name: str
    symbol_type: str = "component"  # component | junction | pin | text_anchor
    bbox: BoundingBox
    confidence: float = 0.0
    value: str = ""
    pins: list[str] = Field(default_factory=list)


class NetEdge(BaseModel):
    source_id: str
    target_id: str
    net_name: str = ""
    relationship: str = "connects"
    spatial_weight: float = 1.0
    evidence: str = ""


class SpatialNetlist(BaseModel):
    figure_id: str = ""
    page: int = 0
    symbols: list[SymbolInstance] = Field(default_factory=list)
    texts: list[TextInstance] = Field(default_factory=list)
    nets: list[NetEdge] = Field(default_factory=list)
    confidence: float = 0.0
    pipeline: str = "omnish"
    mermaid_architecture: str = ""
    mermaid_dataflow: str = ""
    mermaid_dependency: str = ""


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
    spatial_netlist: SpatialNetlist | None = None


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


class NormalizedParameterRow(BaseModel):
    category: str = ""
    parameter: str = ""
    symbol: str = ""
    conditions: str = ""
    supply: str = ""
    minimum: str = ""
    typical: str = ""
    maximum: str = ""
    unit: str = ""
    original_unit: str = ""
    source_pdf_page: int = 0
    section: str = ""


class BlockComponent(BaseModel):
    id: str
    name: str
    type: str = "block"


class ExternalSignal(BaseModel):
    name: str
    direction: str = ""
    function: str = ""


class BlockRelationship(BaseModel):
    source: str
    target: str
    relationship: str = ""
    evidence: str = ""
    confidence: str = "medium"
    source_pdf_page: int = 0


class BlockDiagramWarning(BaseModel):
    type: str = ""
    relationship: str = ""
    action: str = ""


class BlockDiagramEvidence(BaseModel):
    page: int = 0
    figure_id: str = ""
    components: list[BlockComponent] = Field(default_factory=list)
    external_signals: list[ExternalSignal] = Field(default_factory=list)
    relationships: list[BlockRelationship] = Field(default_factory=list)
    warnings: list[BlockDiagramWarning] = Field(default_factory=list)
    confidence: float = 0.0


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
    structured_specification: str = ""
    canonical_spec: dict[str, Any] = Field(default_factory=dict)
    extraction_report: dict[str, Any] = Field(default_factory=dict)
    relationships_csv: str = ""
    electrical_characteristics_csv: str = ""
    block_diagram_evidence: list[BlockDiagramEvidence] = Field(default_factory=list)
    spatial_netlists: list[SpatialNetlist] = Field(default_factory=list)
    normalized_parameters: list[NormalizedParameterRow] = Field(default_factory=list)
