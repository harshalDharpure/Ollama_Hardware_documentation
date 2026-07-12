"""NSC (Near Sight Correction) full diagram pipeline."""

from __future__ import annotations

from pathlib import Path

from src.diagram.classifier import classify_diagram
from src.diagram.connectivity import draw_connectivity_overlay, refine_equipotential_labels
from src.diagram.keypoint_labeler import label_keypoints
from src.diagram.mermaid_from_diagram import generate_mermaid_from_diagram
from src.diagram.yolo_detector import detect_elements
from src.graph.schema import sanitize_id
from src.llm.ollama_client import OllamaClient
from src.models import DiagramResult, DiagramType, ExtractedFigure, HDAEdge


def run_nsc_pipeline(
    client: OllamaClient,
    figure: ExtractedFigure,
    work_dir: Path,
    yolo_weights: str | None = None,
    datasheet_mode: bool = False,
) -> DiagramResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    diagram_type = classify_diagram(figure)

    detections = detect_elements(figure.path, yolo_weights)
    confidence = min(1.0, len(detections) / 10.0) if detections else 0.2

    labeled_path, label_map = label_keypoints(
        figure.path,
        detections,
        output_path=work_dir / f"{figure.id}_labeled.png",
    )

    refine_equipotential_labels(figure.path, detections, label_map)
    draw_connectivity_overlay(
        figure.path,
        detections,
        work_dir / f"{figure.id}_connectivity.png",
    )

    if datasheet_mode:
        mermaid = 'graph TD\n    Debug["Internal NSC labels stored in diagram_work only"]'
    else:
        mermaid = generate_mermaid_from_diagram(client, labeled_path, labeled=True)

    nodes_added = [d.class_name + str(i) for i, d in enumerate(detections[:20])]
    edges_added: list[HDAEdge] = []
    components = [d for d in detections if d.class_name == "component"]
    for i in range(len(components) - 1):
        a = sanitize_id(f"{figure.id}_comp_{i}")
        b = sanitize_id(f"{figure.id}_comp_{i + 1}")
        nodes_added.extend([a, b])
        edges_added.append(
            HDAEdge(**{"from": a, "to": b, "type": "CONNECTS", "label": figure.id})
        )

    return DiagramResult(
        figure_id=figure.id,
        diagram_type=diagram_type,
        original_path=figure.path,
        labeled_path=str(labeled_path),
        mermaid_code=mermaid,
        nodes_added=list(dict.fromkeys(nodes_added)),
        edges_added=edges_added,
        pipeline_used="nsc",
        confidence=confidence,
    )


def process_figure(
    client: OllamaClient,
    figure: ExtractedFigure,
    work_dir: Path,
    yolo_weights: str | None = None,
    dense_threshold: int = 40,
    agentic_fn=None,
    datasheet_mode: bool = False,
) -> DiagramResult:
    diagram_type = classify_diagram(figure, dense_threshold)

    if datasheet_mode:
        return run_nsc_pipeline(client, figure, work_dir, yolo_weights, datasheet_mode=True)

    if diagram_type == DiagramType.DENSE_COMPLEX and agentic_fn:
        return agentic_fn(client, figure, work_dir)

    if diagram_type in (DiagramType.SCHEMATIC, DiagramType.BLOCK_DIAGRAM, DiagramType.DENSE_COMPLEX):
        return run_nsc_pipeline(client, figure, work_dir, yolo_weights, datasheet_mode=False)

    return run_nsc_pipeline(client, figure, work_dir, yolo_weights, datasheet_mode=False)
