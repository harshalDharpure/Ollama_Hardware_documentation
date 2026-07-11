"""Smoke tests for ingestion and graph building (no Ollama required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.decomposer import _fallback_modules
from src.graph.kg_builder import build_kg_from_plan
from src.ingestion.loader import load_document
from src.models import ImplementationPlan, ModuleSpec
from src.output.markdown_builder import build_markdown
from src.output.mermaid_builder import (
    build_architecture_mermaid,
    build_dataflow_mermaid,
    build_dependency_mermaid,
)


SAMPLE = ROOT / "data" / "samples" / "sample_riscv_spec.txt"


def test_load_sample_txt():
    assert SAMPLE.exists(), "Sample spec missing"
    doc = load_document(SAMPLE, work_dir=ROOT / "data" / "output" / "test")
    assert doc.format == "txt"
    assert len(doc.sections) >= 1
    assert "RISC" in doc.raw_text or "Register" in doc.raw_text


def test_fallback_modules():
    doc = load_document(SAMPLE, work_dir=ROOT / "data" / "output" / "test2")
    modules = _fallback_modules(doc)
    assert len(modules) >= 1
    names = {m.name for m in modules}
    assert any("ALU" in n or "Register" in n or "Top" in n for n in names)


def test_kg_and_outputs():
    plan = ImplementationPlan(
        target_function="RV32I",
        modules=[
            ModuleSpec(
                name="ALU",
                description="Arithmetic logic unit",
                inputs=["operand1 (32-bit)", "operand2 (32-bit)"],
                outputs=["result (32-bit)"],
                functionality="Performs ADD, SUB, AND, OR",
                valid=True,
            ),
            ModuleSpec(
                name="RegisterFile",
                description="Register file",
                inputs=["read_addr1 (5-bit)"],
                outputs=["read_data1 (32-bit)"],
                dependencies=["ALU"],
                valid=True,
            ),
        ],
    )
    kg = build_kg_from_plan(plan)
    assert len(kg.nodes) >= 2
    assert len(kg.edges) >= 1

    md = build_markdown(plan, kg)
    assert "ALU" in md
    assert "RegisterFile" in md

    arch = build_architecture_mermaid(kg)
    assert "graph" in arch

    flow = build_dataflow_mermaid(kg)
    assert "flowchart" in flow

    dep = build_dependency_mermaid(kg)
    assert "graph" in dep
