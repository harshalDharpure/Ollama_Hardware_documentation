"""OmniSch-style schematic-to-spatial-netlist pipeline."""

from __future__ import annotations

from pathlib import Path

from src.diagram.keypoint_labeler import label_keypoints
from src.diagram.netlist_to_evidence import netlist_to_block_evidence
from src.diagram.netlist_to_mermaid import enrich_netlist_mermaid
from src.diagram.omnish_agent import run_omnish_agent
from src.diagram.spatial_netlist import build_spatial_netlist
from src.diagram.yolo_detector import detect_elements
from src.graph.schema import sanitize_id
from src.llm.ollama_client import OllamaClient
from src.models import DiagramResult, DiagramType, ExtractedFigure, HDAEdge, SpatialNetlist
from src.output.mermaid_sanitizer import sanitize_mermaid


def run_omnish_pipeline(
    client: OllamaClient,
    figure: ExtractedFigure,
    work_dir: Path,
    diagram_type: DiagramType,
    yolo_weights: str | None = None,
    max_agent_steps: int = 6,
    use_agent: bool = True,
) -> tuple[DiagramResult, SpatialNetlist]:
    work_dir.mkdir(parents=True, exist_ok=True)
    path = Path(figure.path)

    detections = detect_elements(path, yolo_weights=yolo_weights)
    labeled_path, _ = label_keypoints(
        path,
        detections,
        output_path=work_dir / f"{figure.id}_omnish_labeled.png",
    )

    extra_nets = []
    if use_agent and diagram_type in (DiagramType.SCHEMATIC, DiagramType.DENSE_COMPLEX):
        agent_nets, _ = run_omnish_agent(
            client,
            path,
            work_dir / "agent",
            max_steps=max_agent_steps,
            yolo_weights=yolo_weights,
        )
        extra_nets = agent_nets

    netlist = build_spatial_netlist(
        figure_id=figure.id,
        image_path=path,
        page=figure.page or 0,
        yolo_weights=yolo_weights,
        extra_nets=extra_nets,
        diagram_type=diagram_type,
    )
    netlist = enrich_netlist_mermaid(netlist)

    mermaid = netlist.mermaid_architecture or netlist.mermaid_dataflow
    if not mermaid:
        mermaid = 'graph TD\n    Empty["No spatial netlist generated"]'

    nodes_added = [s.name for s in netlist.symbols[:30]]
    edges_added = [
        HDAEdge(
            **{
                "from": sanitize_id(n.source_id),
                "to": sanitize_id(n.target_id),
                "type": "CONNECTS",
                "label": n.net_name or n.relationship,
                "properties": {"spatial_weight": n.spatial_weight},
            }
        )
        for n in netlist.nets[:50]
    ]

    result = DiagramResult(
        figure_id=figure.id,
        diagram_type=diagram_type,
        original_path=str(path),
        labeled_path=str(labeled_path),
        mermaid_code=sanitize_mermaid(mermaid),
        nodes_added=nodes_added,
        edges_added=edges_added,
        pipeline_used="omnish",
        confidence=netlist.confidence,
        spatial_netlist=netlist,
    )
    return result, netlist


def spatial_netlists_to_block_evidence(netlists: list[SpatialNetlist]):
    from src.diagram.block_diagram_extractor import merge_block_evidence

    evidence = [netlist_to_block_evidence(nl) for nl in netlists if nl.symbols or nl.nets]
    return merge_block_evidence(evidence) if evidence else None
