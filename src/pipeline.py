"""End-to-end spec conversion pipeline."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from src.agents.auditor import audit_with_retry
from src.agents.datasheet_synthesizer import synthesize_datasheet_deliverables
from src.agents.decomposer import decompose_modules
from src.agents.specifier import specify_all_modules
from src.agents.summarizer import summarize_sections
from src.config import get_config
from src.diagram.agentic_search import run_agentic_pipeline
from src.diagram.block_diagram_extractor import extract_block_diagram, merge_block_evidence
from src.diagram.classifier import classify_diagram
from src.diagram.omnish_pipeline import run_omnish_pipeline, spatial_netlists_to_block_evidence
from src.diagram.spatial_netlist import merge_spatial_netlists
from src.diagram.nsc_pipeline import process_figure
from src.graph.kg_builder import build_kg_from_plan
from src.graph.merger import merge_diagram_results
from src.ingestion.loader import load_document
from src.ingestion.table_normalizer import normalize_document_tables
from src.llm.ollama_client import OllamaClient, resolve_ollama_models
from src.models import (
    BlockDiagramEvidence,
    DiagramType,
    ImplementationPlan,
    PipelineResult,
    QualityReport,
    SpatialNetlist,
)
from src.output.exporter import export_results
from src.output.markdown_builder import build_markdown
from src.output.mermaid_builder import (
    build_architecture_mermaid,
    build_dataflow_mermaid,
    build_dependency_mermaid,
    combine_diagram_mermaids,
)
from src.output.mermaid_sanitizer import is_valid_mermaid, sanitize_mermaid


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
        diagrams_generated=sum(
            1 for d in result.diagram_results
            if d.mermaid_code and "Error" not in d.mermaid_code and "Empty" not in d.mermaid_code
        ),
        conflicts=[],
    )


def compute_datasheet_quality(
    result: PipelineResult,
    block_evidence: BlockDiagramEvidence | None = None,
) -> QualityReport:
    """Score datasheet deliverables instead of RTL module audit results."""
    doc = result.document
    block = block_evidence or BlockDiagramEvidence()
    preliminary = compute_quality(result.plan, result)

    def _diagram_ok(code: str) -> bool:
        return bool(code) and "Empty" not in code and "Unavailable" not in code and is_valid_mermaid(code)

    checks = [
        len(doc.pages) > 0,
        len(doc.tables) > 0,
        len(doc.figures) > 0,
        bool(result.structured_specification and len(result.structured_specification) > 100),
        bool(result.canonical_spec),
        len(result.normalized_parameters) > 0,
        _diagram_ok(result.architecture_mermaid),
        _diagram_ok(result.dataflow_mermaid),
        _diagram_ok(result.dependency_mermaid),
        len(block.components) > 0 or len(block.relationships) > 0,
    ]
    completeness = sum(checks) / len(checks)

    blocks = len(block.components)
    rels = len(block.relationships)
    modules_valid = blocks if blocks else rels
    modules_total = max(blocks, len(result.plan.modules), 1)

    deliverable_diagrams = sum(
        1
        for code in (result.architecture_mermaid, result.dataflow_mermaid, result.dependency_mermaid)
        if _diagram_ok(code)
    )

    diagram_fidelity = preliminary.diagram_fidelity
    if not diagram_fidelity and block.confidence:
        diagram_fidelity = block.confidence

    return QualityReport(
        completeness_score=round(completeness, 3),
        section_coverage=preliminary.section_coverage,
        modules_valid=modules_valid,
        modules_total=modules_total,
        diagram_fidelity=round(diagram_fidelity, 3),
        pages_processed=len(doc.pages),
        tables_extracted=len(doc.tables),
        figures_extracted=len(doc.figures),
        diagrams_generated=deliverable_diagrams or preliminary.diagrams_generated,
        conflicts=[],
    )


def _make_client(cfg: dict, ollama_base_url: str | None, text_model: str | None, vision_model: str | None) -> OllamaClient:
    ollama_cfg = cfg.get("ollama", {})
    base_url = ollama_base_url or ollama_cfg.get("base_url", "http://localhost:11434")
    requested_text = text_model or ollama_cfg.get("text_model", "qwen2.5:7b")
    requested_vision = vision_model or ollama_cfg.get("vision_model", "llava:7b")
    resolved_text, resolved_vision, _ = resolve_ollama_models(
        base_url=base_url,
        text_model=requested_text,
        vision_model=requested_vision,
        text_fallback=ollama_cfg.get("text_model_fallback"),
        vision_fallback=ollama_cfg.get("vision_model_fallback"),
    )
    return OllamaClient(
        base_url=base_url,
        text_model=resolved_text,
        vision_model=resolved_vision,
        timeout=ollama_cfg.get("timeout", 600),
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
    pipeline_mode: str | None = None,
    omnish_enabled: bool | None = None,
) -> PipelineResult:
    cfg = get_config()
    if omnish_enabled is not None:
        cfg = {**cfg, "pipeline": {**cfg.get("pipeline", {}), "omnish_enabled": omnish_enabled}}
    mode = pipeline_mode or cfg.get("pipeline", {}).get("mode", "datasheet")
    path = Path(document_path)

    if mode == "datasheet" or path.suffix.lower() == ".pdf":
        return _run_datasheet_pipeline(
            document_path=path,
            work_dir=work_dir,
            progress_callback=progress_callback,
            ollama_base_url=ollama_base_url,
            text_model=text_model,
            vision_model=vision_model,
            yolo_weights=yolo_weights,
            process_all_diagrams=process_all_diagrams,
            cfg=cfg,
        )
    return _run_rtl_pipeline(
        document_path=path,
        work_dir=work_dir,
        progress_callback=progress_callback,
        ollama_base_url=ollama_base_url,
        text_model=text_model,
        vision_model=vision_model,
        yolo_weights=yolo_weights,
        process_all_diagrams=process_all_diagrams,
        cfg=cfg,
    )


def _run_datasheet_pipeline(
    document_path: Path,
    work_dir: str | Path | None,
    progress_callback: Callable[[str, float], None] | None,
    ollama_base_url: str | None,
    text_model: str | None,
    vision_model: str | None,
    yolo_weights: str | None,
    process_all_diagrams: bool,
    cfg: dict,
) -> PipelineResult:
    diagram_cfg = cfg.get("diagram", {})
    pipeline_cfg = cfg.get("pipeline", {})
    client = _make_client(cfg, ollama_base_url, text_model, vision_model)

    base_work = Path(work_dir or cfg.get("output", {}).get("work_dir", "data/output"))
    base_work.mkdir(parents=True, exist_ok=True)
    session_dir = base_work / document_path.stem
    session_dir.mkdir(parents=True, exist_ok=True)

    def progress(msg: str, pct: float) -> None:
        if progress_callback:
            progress_callback(msg, pct)

    progress("Loading & scanning PDF page-by-page...", 0.05)
    yolo_device = diagram_cfg.get("yolo_device", "cpu")
    if yolo_device:
        os.environ["YOLO_DEVICE"] = str(yolo_device)
    document = load_document(document_path, work_dir=session_dir)
    progress(
        f"Found {len(document.pages)} pages, {len(document.tables)} tables, {len(document.figures)} figures",
        0.10,
    )

    progress("Normalizing electrical parameter tables...", 0.15)
    normalized_parameters = normalize_document_tables(document)

    progress("Summarizing sections...", 0.22)
    summaries = summarize_sections(client, document)

    progress("Extracting diagrams (OmniSch + semantic block evidence)...", 0.35)
    block_pages_only = pipeline_cfg.get("datasheet_block_pages_only", True)
    omnish_enabled = pipeline_cfg.get("omnish_enabled", True)
    figures_to_process = document.figures
    if block_pages_only:
        diagram_page_nums = {p.page_num for p in document.pages if p.is_diagram_page}
        figures_to_process = [
            f for f in document.figures
            if f.source_type == "page_render" and (f.page in diagram_page_nums or not diagram_page_nums)
        ]

    block_evidence_list: list[BlockDiagramEvidence] = []
    spatial_netlists = []
    diagram_results = []
    fig_work = session_dir / "diagram_work"
    yolo_weights = yolo_weights or diagram_cfg.get("yolo_weights")
    dense_threshold = diagram_cfg.get("dense_symbol_threshold", 40)
    max_steps = diagram_cfg.get("agentic_max_steps", 4)
    omnish_agent_steps = diagram_cfg.get("omnish_agent_steps", 6)

    total_figs = max(len(figures_to_process), 1)
    for i, figure in enumerate(figures_to_process):
        progress(f"Diagram {i + 1}/{total_figs}: {figure.id}", 0.35 + 0.25 * (i / total_figs))
        diagram_type = classify_diagram(figure, dense_threshold)

        evidence = extract_block_diagram(client, figure, diagram_type, force=True)
        if evidence:
            block_evidence_list.append(evidence)

        if omnish_enabled:
            dr, netlist = run_omnish_pipeline(
                client=client,
                figure=figure,
                work_dir=fig_work / figure.id / "omnish",
                diagram_type=diagram_type,
                yolo_weights=yolo_weights,
                max_agent_steps=omnish_agent_steps,
                use_agent=diagram_type in (DiagramType.SCHEMATIC, DiagramType.DENSE_COMPLEX),
            )
            diagram_results.append(dr)
            spatial_netlists.append(netlist)
            omnish_evidence = spatial_netlists_to_block_evidence([netlist])
            if omnish_evidence and omnish_evidence.components:
                block_evidence_list.append(omnish_evidence)

        elif process_all_diagrams and not block_pages_only:
            dr = process_figure(
                client,
                figure,
                fig_work / figure.id,
                yolo_weights=yolo_weights,
                dense_threshold=dense_threshold,
                agentic_fn=lambda c, f, w: run_agentic_pipeline(c, f, w, max_steps=max_steps),
                datasheet_mode=True,
            )
            diagram_results.append(dr)

    merged_block = merge_block_evidence(block_evidence_list)
    merged_spatial = _select_spatial_netlist(spatial_netlists)

    progress("Building lightweight module graph for traceability...", 0.65)
    target, modules = decompose_modules(client, document, summaries)
    plan = ImplementationPlan(
        target_function=target,
        modules=modules,
        section_summaries=summaries,
    )
    kg = build_kg_from_plan(plan)

    if diagram_results:
        for dr in diagram_results:
            dr.mermaid_code = sanitize_mermaid(dr.mermaid_code)
        kg = merge_diagram_results(kg, diagram_results)

    markdown = build_markdown(plan, kg, document=document)
    combined_mmd = sanitize_mermaid(combine_diagram_mermaids(diagram_results, title=document.title))

    preliminary = PipelineResult(
        document=document,
        plan=plan,
        knowledge_graph=kg,
        markdown=markdown,
        combined_diagram_mermaid=combined_mmd,
        diagram_results=diagram_results,
        block_diagram_evidence=block_evidence_list,
        normalized_parameters=normalized_parameters,
    )
    preliminary.quality = compute_quality(plan, preliminary)

    progress("Synthesizing hackathon datasheet deliverables...", 0.85)
    deliverables = synthesize_datasheet_deliverables(
        client=client,
        document=document,
        summaries=summaries,
        block_evidence=merged_block,
        normalized_parameters=normalized_parameters,
        quality=preliminary.quality,
        title=target,
        spatial_netlist=merged_spatial,
    )

    result = PipelineResult(
        document=document,
        plan=plan,
        knowledge_graph=kg,
        markdown=deliverables.get("specification") or markdown,
        architecture_mermaid=deliverables.get("architecture_mermaid", ""),
        dataflow_mermaid=deliverables.get("dataflow_mermaid", ""),
        dependency_mermaid=deliverables.get("dependency_mermaid", ""),
        combined_diagram_mermaid=combined_mmd,
        diagram_results=diagram_results,
        structured_specification=deliverables.get("specification", ""),
        canonical_spec=deliverables.get("canonical_spec", {}),
        extraction_report=deliverables.get("extraction_report", {}),
        relationships_csv=deliverables.get("relationships_csv", ""),
        electrical_characteristics_csv=deliverables.get("electrical_characteristics_csv", ""),
        block_diagram_evidence=block_evidence_list,
        spatial_netlists=spatial_netlists,
        normalized_parameters=normalized_parameters,
    )
    result.quality = compute_datasheet_quality(result, merged_block)

    progress("Exporting results...", 0.95)
    export_dir = export_results(result, session_dir / "export")
    result.export_dir = export_dir

    progress("Complete", 1.0)
    return result


def _select_spatial_netlist(netlists: list[SpatialNetlist]) -> SpatialNetlist | None:
    """Pick a compact spatial netlist; skip merged graphs that are too dense for Mermaid."""
    if not netlists:
        return None

    merged = merge_spatial_netlists(netlists)
    if len(merged.nets) <= 50 and len(merged.symbols) <= 30:
        return merged

    best = min(netlists, key=lambda nl: (len(nl.nets), len(nl.symbols)))
    if len(best.nets) > 50:
        return None
    return best


def _run_rtl_pipeline(
    document_path: Path,
    work_dir: str | Path | None,
    progress_callback: Callable[[str, float], None] | None,
    ollama_base_url: str | None,
    text_model: str | None,
    vision_model: str | None,
    yolo_weights: str | None,
    process_all_diagrams: bool,
    cfg: dict,
) -> PipelineResult:
    diagram_cfg = cfg.get("diagram", {})
    agents_cfg = cfg.get("agents", {})
    client = _make_client(cfg, ollama_base_url, text_model, vision_model)

    base_work = Path(work_dir or cfg.get("output", {}).get("work_dir", "data/output"))
    base_work.mkdir(parents=True, exist_ok=True)
    session_dir = base_work / document_path.stem
    session_dir.mkdir(parents=True, exist_ok=True)

    def progress(msg: str, pct: float) -> None:
        if progress_callback:
            progress_callback(msg, pct)

    progress("Loading document...", 0.05)
    document = load_document(document_path, work_dir=session_dir)

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

    progress(f"Processing {len(figures_to_process)} diagrams...", 0.60)
    diagram_results = []
    fig_work = session_dir / "diagram_work"
    yolo_weights = yolo_weights or diagram_cfg.get("yolo_weights")
    dense_threshold = diagram_cfg.get("dense_symbol_threshold", 40)
    max_steps = diagram_cfg.get("agentic_max_steps", 4)

    total_figs = max(len(figures_to_process), 1)
    for i, figure in enumerate(figures_to_process):
        progress(f"Diagram {i + 1}/{total_figs}: {figure.id}", 0.60 + 0.25 * (i / total_figs))
        dr = process_figure(
            client,
            figure,
            fig_work / figure.id,
            yolo_weights=yolo_weights,
            dense_threshold=dense_threshold,
            agentic_fn=lambda c, f, w: run_agentic_pipeline(c, f, w, max_steps=max_steps),
            datasheet_mode=False,
        )
        diagram_results.append(dr)

    for dr in diagram_results:
        dr.mermaid_code = sanitize_mermaid(dr.mermaid_code)

    kg = merge_diagram_results(kg, diagram_results)

    markdown = build_markdown(plan, kg, document=document)
    arch_mmd = sanitize_mermaid(build_architecture_mermaid(kg))
    flow_mmd = sanitize_mermaid(build_dataflow_mermaid(kg))
    dep_mmd = sanitize_mermaid(build_dependency_mermaid(kg))
    combined_mmd = sanitize_mermaid(combine_diagram_mermaids(diagram_results, title=document.title))

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
