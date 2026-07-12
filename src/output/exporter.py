"""Export pipeline results to hackathon ZIP bundle."""

from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

from src.models import PipelineResult
from src.output.mermaid_sanitizer import sanitize_mermaid

HACKATHON_FILES = (
    "specification.md",
    "canonical_spec.json",
    "architecture.mmd",
    "data_flow.mmd",
    "dependency_graph.mmd",
    "extraction_report.json",
)


def export_results(result: PipelineResult, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(exist_ok=True)

    spec_text = result.structured_specification or result.markdown
    (output_dir / "specification.md").write_text(spec_text, encoding="utf-8")
    (output_dir / "architecture.mmd").write_text(sanitize_mermaid(result.architecture_mermaid), encoding="utf-8")
    (output_dir / "data_flow.mmd").write_text(sanitize_mermaid(result.dataflow_mermaid), encoding="utf-8")
    (output_dir / "dependency_graph.mmd").write_text(sanitize_mermaid(result.dependency_mermaid), encoding="utf-8")
    (output_dir / "canonical_spec.json").write_text(
        json.dumps(result.canonical_spec or {}, indent=2),
        encoding="utf-8",
    )
    (output_dir / "extraction_report.json").write_text(
        json.dumps(result.extraction_report or {}, indent=2),
        encoding="utf-8",
    )

    if result.relationships_csv:
        (output_dir / "relationships.csv").write_text(result.relationships_csv, encoding="utf-8")
    if result.electrical_characteristics_csv:
        (output_dir / "electrical_characteristics.csv").write_text(
            result.electrical_characteristics_csv,
            encoding="utf-8",
        )

    (debug_dir / "hda.json").write_text(
        result.knowledge_graph.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (debug_dir / "quality.json").write_text(
        result.quality.model_dump_json(indent=2),
        encoding="utf-8",
    )
    if result.combined_diagram_mermaid:
        (debug_dir / "combined_diagrams.mmd").write_text(result.combined_diagram_mermaid, encoding="utf-8")
    if result.block_diagram_evidence:
        (debug_dir / "block_diagram_evidence.json").write_text(
            json.dumps([e.model_dump() for e in result.block_diagram_evidence], indent=2),
            encoding="utf-8",
        )
    if result.spatial_netlists:
        (debug_dir / "spatial_netlists.json").write_text(
            json.dumps([n.model_dump() for n in result.spatial_netlists], indent=2),
            encoding="utf-8",
        )
        merged = result.spatial_netlists[0]
        if len(result.spatial_netlists) > 1:
            from src.diagram.spatial_netlist import merge_spatial_netlists
            merged = merge_spatial_netlists(result.spatial_netlists)
        (debug_dir / "spatial_netlist.json").write_text(
            merged.model_dump_json(indent=2),
            encoding="utf-8",
        )

    tables_dir = debug_dir / "tables"
    tables_dir.mkdir(exist_ok=True)
    for t in result.document.tables:
        (tables_dir / f"{t.id}.md").write_text(t.markdown, encoding="utf-8")
        if t.rows:
            with open(tables_dir / f"{t.id}.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(t.rows)

    pages_dir = debug_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for p in result.document.pages:
        (pages_dir / f"page_{p.page_num}.txt").write_text(p.text, encoding="utf-8")

    diag_dir = debug_dir / "diagrams"
    diag_dir.mkdir(exist_ok=True)
    for dr in result.diagram_results:
        (diag_dir / f"{dr.figure_id}.mmd").write_text(dr.mermaid_code, encoding="utf-8")
        if dr.labeled_path and Path(dr.labeled_path).exists():
            labeled_dest = debug_dir / "labeled" / f"{dr.figure_id}_labeled.png"
            labeled_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dr.labeled_path, labeled_dest)

    zip_path = output_dir / "ds3231_hackathon_output.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in HACKATHON_FILES:
            file_path = output_dir / name
            if file_path.exists():
                zf.write(file_path, name)
        for bonus in ("relationships.csv", "electrical_characteristics.csv"):
            file_path = output_dir / bonus
            if file_path.exists():
                zf.write(file_path, bonus)

    legacy_zip = output_dir / "spec_export.zip"
    if legacy_zip.exists():
        legacy_zip.unlink()
    shutil.copy2(zip_path, legacy_zip)

    return str(output_dir)
