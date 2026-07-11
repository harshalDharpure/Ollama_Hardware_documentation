"""OmniSch-style agentic crop/zoom for dense schematics."""

from __future__ import annotations

import json
import re
from pathlib import Path

import cv2

from src.diagram.mermaid_from_diagram import extract_mermaid, generate_mermaid_from_diagram
from src.diagram.yolo_detector import detect_elements
from src.graph.schema import sanitize_id
from src.llm.ollama_client import OllamaClient
from src.models import DiagramResult, DiagramType, ExtractedFigure, HDAEdge


def _ocr_region(image_path: Path, x1: int, y1: int, x2: int, y2: int) -> str:
    img = cv2.imread(str(image_path))
    if img is None:
        return ""
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return ""

    try:
        import pytesseract
        text = pytesseract.image_to_string(crop, config="--psm 7")
        return text.strip()
    except Exception:
        return ""


def run_agentic_pipeline(
    client: OllamaClient,
    figure: ExtractedFigure,
    work_dir: Path,
    max_steps: int = 8,
) -> DiagramResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    path = Path(figure.path)
    detections = detect_elements(figure.path)
    symbols: dict[str, str] = {}
    connections: list[tuple[str, str]] = []

    # Phase 1: OCR symbol names from detection regions
    for i, det in enumerate(detections[:max_steps]):
        text = _ocr_region(path, det.x1, det.y1, det.x2, det.y2)
        name = text.split("\n")[0][:40].strip() if text else f"Sym{i}"
        name = re.sub(r"[^\w\-]", "", name) or f"Sym{i}"
        symbols[f"S{i}"] = name

    # Phase 2: ReAct-style zoom on dense regions
    img = cv2.imread(str(path))
    if img is not None:
        h, w = img.shape[:2]
        grid = 3
        step_w, step_h = w // grid, h // grid
        for step in range(min(max_steps, grid * grid)):
            gx, gy = step % grid, step // grid
            x1, y1 = gx * step_w, gy * step_h
            x2, y2 = x1 + step_w, y1 + step_h
            crop_path = work_dir / f"{figure.id}_crop_{step}.png"
            cv2.imwrite(str(crop_path), img[y1:y2, x1:x2])

            prompt = (
                "List component names and net labels visible in this schematic region. "
                "Respond as JSON: {\"components\": [\"name1\"], \"nets\": [\"net1\"]}"
            )
            try:
                raw = client.chat_vision(prompt, crop_path)
                data = client.parse_json_response(raw)
                for comp in data.get("components", []):
                    symbols[f"Z{step}_{comp}"] = str(comp)
                for j, net in enumerate(data.get("nets", [])[:-1]):
                    nets = data.get("nets", [])
                    if j + 1 < len(nets):
                        connections.append((str(net), str(nets[j + 1])))
            except Exception:
                continue

    # Phase 3: Generate mermaid from full image with accumulated context
    context = json.dumps({"symbols": symbols, "connections": connections})
    try:
        raw = client.chat_vision(
            f"Context from visual search: {context}\n\n"
            + "Generate mermaid graph code for the full schematic connectivity.",
            figure.path,
        )
        mermaid = extract_mermaid(raw)
    except Exception:
        mermaid = generate_mermaid_from_diagram(client, figure.path, labeled=False)

    if not mermaid or "Error" in mermaid:
        mermaid = _build_mermaid_from_symbols(symbols, connections)

    nodes_added = list(symbols.values())
    edges_added = [
        HDAEdge(**{"from": sanitize_id(a), "to": sanitize_id(b), "type": "CONNECTS", "label": "net"})
        for a, b in connections
    ]

    return DiagramResult(
        figure_id=figure.id,
        diagram_type=DiagramType.DENSE_COMPLEX,
        original_path=figure.path,
        labeled_path=figure.path,
        mermaid_code=mermaid,
        nodes_added=nodes_added,
        edges_added=edges_added,
        pipeline_used="agentic",
        confidence=0.5 + 0.05 * len(symbols),
    )


def _build_mermaid_from_symbols(symbols: dict[str, str], connections: list[tuple[str, str]]) -> str:
    lines = ["graph TD"]
    for sid, name in symbols.items():
        nid = sanitize_id(name)
        lines.append(f"    {nid}[\"{name}\"]")
    for a, b in connections:
        lines.append(f"    {sanitize_id(a)} --> {sanitize_id(b)}")
    if len(lines) == 1:
        lines.append('    Empty["No connectivity extracted"]')
    return "\n".join(lines)
