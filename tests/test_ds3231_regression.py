"""Regression tests for DS3231 hackathon deliverable shape."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.datasheet_synthesizer import synthesize_datasheet_deliverables
from src.diagram.block_diagram_extractor import merge_block_evidence
from src.ingestion.loader import load_document
from src.ingestion.table_normalizer import normalize_document_tables
from src.llm.ollama_client import OllamaClient
from src.models import (
    BlockComponent,
    BlockDiagramEvidence,
    BlockRelationship,
    ExternalSignal,
    QualityReport,
)
from src.output.exporter import HACKATHON_FILES, export_results
from src.output.mermaid_sanitizer import sanitize_mermaid
from src.pipeline import run_pipeline

SAMPLE_PDF = ROOT / "data" / "samples" / "ds3231.pdf"


def _mock_block_evidence() -> BlockDiagramEvidence:
    return BlockDiagramEvidence(
        page=8,
        figure_id="page_8",
        components=[
            BlockComponent(id="power_control", name="Power Control", type="power"),
            BlockComponent(id="i2c", name="I2C Interface", type="interface"),
        ],
        external_signals=[
            ExternalSignal(name="VCC", direction="input", function="primary supply"),
            ExternalSignal(name="SCL", direction="input", function="I2C clock"),
        ],
        relationships=[
            BlockRelationship(
                source="VCC",
                target="power_control",
                relationship="powers",
                evidence="block diagram arrow",
                confidence="high",
                source_pdf_page=8,
            )
        ],
        confidence=0.85,
    )


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="DS3231 sample PDF missing")
def test_table_normalizer_finds_parameters():
    doc = load_document(SAMPLE_PDF, work_dir=ROOT / "data" / "output" / "test_norm")
    rows = normalize_document_tables(doc)
    assert len(rows) >= 1
    assert any(r.parameter or r.symbol for r in rows)


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="DS3231 sample PDF missing")
def test_synthesizer_fallback_deliverable_shape():
    doc = load_document(SAMPLE_PDF, work_dir=ROOT / "data" / "output" / "test_synth")
    rows = normalize_document_tables(doc)
    block = _mock_block_evidence()

    class _OfflineClient(OllamaClient):
        def chat_text(self, *args, **kwargs) -> str:
            raise RuntimeError("offline")

        def chat_vision(self, *args, **kwargs) -> str:
            raise RuntimeError("offline")

    deliverables = synthesize_datasheet_deliverables(
        client=_OfflineClient(),
        document=doc,
        summaries=[],
        block_evidence=block,
        normalized_parameters=rows,
        quality=QualityReport(tables_extracted=len(doc.tables), pages_processed=len(doc.pages)),
        title="DS3231",
    )

    spec = deliverables["specification"]
    assert "DS3231" in spec
    assert "J1" not in spec and "J2" not in spec

    canonical = deliverables["canonical_spec"]
    assert "components" in canonical
    assert "relationships" in canonical
    assert "electrical_characteristics" in canonical

    for key in ("architecture_mermaid", "dataflow_mermaid", "dependency_mermaid"):
        code = deliverables[key]
        assert "J1" not in code and "J2" not in code
        assert "Unavailable" not in code
        sanitized = sanitize_mermaid(code)
        assert sanitized.startswith(("graph", "flowchart"))
        assert "Power Control" in code or "VCC" in code

    report = deliverables["extraction_report"]
    assert "confidence" in report
    assert "warnings" in report
    assert report["deliverables"] == list(HACKATHON_FILES)


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="DS3231 sample PDF missing")
def test_exporter_writes_hackathon_files(tmp_path):
    from src.models import DocumentBundle, ImplementationPlan, KnowledgeGraph, PipelineResult

    result = PipelineResult(
        document=DocumentBundle(source_path=str(SAMPLE_PDF), format="pdf", title="DS3231"),
        plan=ImplementationPlan(target_function="DS3231"),
        knowledge_graph=KnowledgeGraph(),
        structured_specification="# DS3231 Hardware Specification",
        architecture_mermaid='flowchart LR\n    A["Power Control"]',
        dataflow_mermaid='flowchart LR\n    B["I2C Bus"]',
        dependency_mermaid='graph TD\n    C["Oscillator"]',
        canonical_spec={"document": {"device": "DS3231"}, "components": [], "relationships": []},
        extraction_report={"document_id": "DS3231", "confidence": {}, "warnings": []},
    )
    export_dir = tmp_path / "export"
    export_results(result, export_dir)

    for name in HACKATHON_FILES:
        assert (export_dir / name).exists(), f"missing {name}"

    assert (export_dir / "ds3231_hackathon_output.zip").exists()
    assert (export_dir / "debug" / "hda.json").exists()
    assert "J1" not in (export_dir / "specification.md").read_text()


def test_merge_block_evidence_deduplicates():
    a = BlockDiagramEvidence(
        components=[BlockComponent(id="osc", name="Oscillator", type="clock")],
        relationships=[BlockRelationship(source="osc", target="div", relationship="clocks")],
    )
    b = BlockDiagramEvidence(
        components=[BlockComponent(id="osc", name="Oscillator", type="clock")],
        relationships=[BlockRelationship(source="div", target="cal", relationship="1hz")],
    )
    merged = merge_block_evidence([a, b])
    assert len(merged.components) == 1
    assert len(merged.relationships) == 2


@pytest.mark.integration
@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="DS3231 sample PDF missing")
def test_full_pipeline_integration():
    client = OllamaClient()
    health = client.health_check()
    if not health.get("ok"):
        pytest.skip("Ollama not available")

    result = run_pipeline(
        SAMPLE_PDF,
        work_dir=ROOT / "data" / "output" / "test_integration",
        process_all_diagrams=False,
    )
    export_dir = Path(result.export_dir)
    for name in HACKATHON_FILES:
        assert (export_dir / name).exists(), f"missing {name}"

    spec = (export_dir / "specification.md").read_text()
    assert "J1" not in spec and "J2" not in spec

    canonical = json.loads((export_dir / "canonical_spec.json").read_text())
    assert "components" in canonical
    assert "relationships" in canonical

    report = json.loads((export_dir / "extraction_report.json").read_text())
    assert "confidence" in report
