"""End-to-end spec conversion pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.agents.auditor import audit_with_retry
from src.agents.decomposer import decompose_modules
from src.agents.specifier import specify_all_modules
from src.agents.summarizer import summarize_sections
from src.config import get_config
from src.diagram.agentic_search import run_agentic_pipeline
from src.diagram.nsc_pipeline import process_figure
from src.graph.kg_builder import build_kg_from_plan
from src.graph.merger import merge_diagram_results
from src.ingestion.loader import load_document
from src.llm.ollama_client import OllamaClient
from src.models import ImplementationPlan, PipelineResult, QualityReport
from src.output.exporter import export_results
from src.output.markdown_builder import build_markdown
from src.output.mermaid_builder import (
    build_architecture_mermaid,
    build_dataflow_mermaid,
    build_dependency_mermaid,
    combine_diagram_mermaids,
)


def compute_quality(plan: ImplementationPlan, result: PipelineResult) -> QualityReport:
    modules_total = len(plan.modules)
    modules_valid = sum(1 for m in plan.modules if m.valid)
    completeness = modules_valid / modules_total if modules_total else 0.0

    sections_total = len(plan.section_summaries)
    section_refs = sum(1 for n in result.knowledge_graph.nodes if n.spec_ref)
    coverage = section_refs / max(sections_total, 1)

    diagram_fidelity = 0.0
    if result.diagram_results:
        diagram_fidelity = sum(dr.confidence for dr in result.diagram_results) / len(result.diagram_results)

    doc = result.document
    return QualityReport(
        completeness_score=round(completeness, 3),
        section_coverage=round(min(coverage, 1.0), 3),
        modules_valid=modules_valid,
        modules_total=modules_total,
        diagram_fidelity=round(diagram_fidelity, 3),
        pages_processed=len(doc.pages),
        tables_extracted=len(doc.tables),
        figures_extracted=len(doc.figures),
        diagrams_generated=sum(1 for d in result.diagram_results if d.mermaid_code and "Error" not in d.mermaid_code),
        conflicts=[],
    )


def run_pipeline(
    document_path: str | Path,
    work_dir: str | Path | None = None,
    progress_callback: Callable[[str, float], None] | None = None,
    ollama_base_url: str | None = None,
    text_model: str | None = None,
    vision_model: str | None = None,
    yolo_weights: str | None = None,
    process_all_diagrams: bool = True,
) -> PipelineResult:
    cfg = get_config()
    ollama_cfg = cfg.get("ollama", {})
    diagram_cfg = cfg.get("diagram", {})
    agents_cfg = cfg.get("agents", {})

    client = OllamaClient(
        base_url=ollama_base_url or ollama_cfg.get("base_url", "http://localhost:11434"),
        text_model=text_model or ollama_cfg.get("text_model", "qwen2.5:7b"),
        vision_model=vision_model or ollama_cfg.get("vision_model", "llava:13b"),
        timeout=ollama_cfg.get("timeout", 300),
    )

    base_work = Path(work_dir or cfg.get("output", {}).get("work_dir", "data/output"))
    base_work.mkdir(parents=True, exist_ok=True)
    session_dir = base_work / Path(document_path).stem
    session_dir.mkdir(parents=True, exist_ok=True)

    def progress(msg: str, pct: float) -> None:
        if progress_callback:
            progress_callback(msg, pct)

    progress("Loading & scanning PDF page-by-page...", 0.05)
    document = load_document(document_path, work_dir=session_dir)
    progress(
        f"Found {len(document.pages)} pages, {len(document.tables)} tables, {len(document.figures)} figures",
        0.10,
    )

    progress("Summarizing sections...", 0.15)
    summaries = summarize_sections(client, document)

    progress("Decomposing modules...", 0.25)
    target, modules = decompose_modules(client, document, summaries)

    progress("Specifying module interfaces...", 0.35)
    modules = specify_all_modules(client, document, modules)

    progress("Auditing specifications...", 0.45)
    modules = audit_with_retry(
        client,
        document,
        modules,
        specify_fn=None,
        max_retries=agents_cfg.get("auditor_max_retries", 2),
    )

    plan = ImplementationPlan(
        target_function=target,
        modules=modules,
        section_summaries=summaries,
    )

    progress("Building knowledge graph...", 0.55)
    kg = build_kg_from_plan(plan)

    figures_to_process = document.figures
    if not process_all_diagrams:
        figures_to_process = [f for f in document.figures if f.source_type == "embedded"]

    progress(f"Processing {len(figures_to_process)} diagrams (NSC + agentic)...", 0.60)
    diagram_results = []
    fig_work = session_dir / "diagram_work"
    yolo_weights = yolo_weights or diagram_cfg.get("yolo_weights")
    dense_threshold = diagram_cfg.get("dense_symbol_threshold", 40)
    max_steps = diagram_cfg.get("agentic_max_steps", 8)

    total_figs = max(len(figures_to_process), 1)
    for i, figure in enumerate(figures_to_process):
        progress(
            f"Diagram {i + 1}/{total_figs}: {figure.id} (page {figure.page})",
            0.60 + 0.25 * (i / total_figs),
        )
        dr = process_figure(
            client,
            figure,
            fig_work / figure.id,
            yolo_weights=yolo_weights,
            dense_threshold=dense_threshold,
            agentic_fn=lambda c, f, w: run_agentic_pipeline(c, f, w, max_steps=max_steps),
        )
        diagram_results.append(dr)

    progress("Merging diagram knowledge...", 0.88)
    kg = merge_diagram_results(kg, diagram_results)

    markdown = build_markdown(plan, kg, document=document)
    arch_mmd = build_architecture_mermaid(kg)
    flow_mmd = build_dataflow_mermaid(kg)
    dep_mmd = build_dependency_mermaid(kg)
    combined_mmd = combine_diagram_mermaids(diagram_results, title=document.title)

    result = PipelineResult(
        document=document,
        plan=plan,
        knowledge_graph=kg,
        markdown=markdown,
        architecture_mermaid=arch_mmd,
        dataflow_mermaid=flow_mmd,
        dependency_mermaid=dep_mmd,
        combined_diagram_mermaid=combined_mmd,
        diagram_results=diagram_results,
    )
    result.quality = compute_quality(plan, result)

    progress("Exporting results...", 0.95)
    export_dir = export_results(result, session_dir / "export")
    result.export_dir = export_dir

    progress("Complete", 1.0)
    return result
