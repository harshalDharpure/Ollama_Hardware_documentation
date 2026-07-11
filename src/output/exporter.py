"""Export pipeline results to ZIP bundle."""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from src.models import PipelineResult


def export_results(result: PipelineResult, output_dir: Path) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "spec.md").write_text(result.markdown, encoding="utf-8")
    (output_dir / "architecture.mmd").write_text(result.architecture_mermaid, encoding="utf-8")
    (output_dir / "dataflow.mmd").write_text(result.dataflow_mermaid, encoding="utf-8")
    (output_dir / "dependency.mmd").write_text(result.dependency_mermaid, encoding="utf-8")
    (output_dir / "combined_diagrams.mmd").write_text(result.combined_diagram_mermaid, encoding="utf-8")
    (output_dir / "hda.json").write_text(
        result.knowledge_graph.model_dump_json(indent=2),
        encoding="utf-8",
    )
    (output_dir / "quality.json").write_text(
        result.quality.model_dump_json(indent=2),
        encoding="utf-8",
    )

    tables_dir = output_dir / "tables"
    tables_dir.mkdir(exist_ok=True)
    for t in result.document.tables:
        (tables_dir / f"{t.id}.md").write_text(t.markdown, encoding="utf-8")
        if t.rows:
            with open(tables_dir / f"{t.id}.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(t.rows)

    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for p in result.document.pages:
        (pages_dir / f"page_{p.page_num}.txt").write_text(p.text, encoding="utf-8")

    diag_dir = output_dir / "diagrams"
    diag_dir.mkdir(exist_ok=True)
    for dr in result.diagram_results:
        (diag_dir / f"{dr.figure_id}.mmd").write_text(dr.mermaid_code, encoding="utf-8")

    zip_path = output_dir / "spec_export.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in output_dir.rglob("*"):
            if f.is_file() and f.suffix != ".zip":
                zf.write(f, f.relative_to(output_dir))

    return str(output_dir)
