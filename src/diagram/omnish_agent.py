"""ReAct-style agentic visual search for dense schematics (OmniSch-inspired)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import cv2

from src.diagram.ocr_extractor import extract_text_instances, ocr_region
from src.diagram.yolo_detector import detect_elements
from src.llm.ollama_client import OllamaClient
from src.models import BoundingBox, NetEdge


AGENT_SYSTEM = """You are a schematic analysis agent. Choose ONE tool per step to
extract connectivity from a circuit diagram. Respond ONLY with JSON:
{"tool": "...", "args": {...}, "done": false}
or when finished:
{"tool": "finish", "args": {}, "done": true, "connections": [{"source":"", "target":"", "net":""}]}
Available tools: crop_inspect, ocr_full, detect_symbols, list_regions."""


def run_omnish_agent(
    client: OllamaClient,
    image_path: str | Path,
    work_dir: Path,
    max_steps: int = 6,
    yolo_weights: str | None = None,
) -> tuple[list[NetEdge], dict[str, str]]:
    path = Path(image_path)
    work_dir.mkdir(parents=True, exist_ok=True)
    symbols: dict[str, str] = {}
    connections: list[NetEdge] = []
    context: list[str] = []

    img = cv2.imread(str(path))
    if img is None:
        return connections, symbols

    h, w = img.shape[:2]
    detections = detect_elements(path, yolo_weights=yolo_weights)
    for i, det in enumerate(detections[:30]):
        name = det.class_name
        hit = ocr_region(path, BoundingBox(x1=det.x1, y1=det.y1, x2=det.x2, y2=det.y2))
        if hit and hit.text:
            name = hit.text
        sid = _slug(name, f"sym_{i}")
        symbols[sid] = name

    texts = extract_text_instances(path)
    for t in texts[:20]:
        sid = _slug(t.text, "text")
        symbols[sid] = t.text

    for step in range(max_steps):
        prompt = (
            f"Step {step + 1}/{max_steps}. Image size {w}x{h}.\n"
            f"Known symbols: {json.dumps(symbols)}\n"
            f"Context: {json.dumps(context[-6:])}\n"
            "Pick the next tool to find more connections."
        )
        try:
            raw = client.chat_text(prompt, system=AGENT_SYSTEM, json_mode=True)
            action = client.parse_json_response(raw)
        except Exception:
            break

        tool = str(action.get("tool", "")).lower()
        args = action.get("args", {}) or {}
        if action.get("done") or tool == "finish":
            for item in action.get("connections", []):
                src = _slug(str(item.get("source", "")), "src")
                dst = _slug(str(item.get("target", "")), "dst")
                if src and dst:
                    connections.append(
                        NetEdge(
                            source_id=src,
                            target_id=dst,
                            net_name=str(item.get("net", "")),
                            relationship="agentic_connect",
                            spatial_weight=0.75,
                            evidence=f"agent_step_{step}",
                        )
                    )
                    symbols.setdefault(src, str(item.get("source", src)))
                    symbols.setdefault(dst, str(item.get("target", dst)))
            break

        if tool == "crop_inspect":
            gx = int(args.get("grid_x", step % 3))
            gy = int(args.get("grid_y", step // 3))
            crop_path, summary = _crop_inspect(client, img, work_dir, gx, gy, w, h)
            context.append(summary)
        elif tool == "ocr_full":
            context.append(f"ocr_full: {[t.text for t in texts[:15]]}")
        elif tool == "detect_symbols":
            context.append(f"detect_symbols: {list(symbols.values())[:20]}")
        elif tool == "list_regions":
            regions = [
                {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2, "class": d.class_name}
                for d in detections[:12]
            ]
            context.append(f"list_regions: {regions}")
        else:
            break

    return connections, symbols


def _crop_inspect(
    client: OllamaClient,
    img,
    work_dir: Path,
    gx: int,
    gy: int,
    w: int,
    h: int,
) -> tuple[Path, str]:
    grid = 3
    step_w, step_h = max(1, w // grid), max(1, h // grid)
    x1, y1 = gx * step_w, gy * step_h
    x2, y2 = min(w, x1 + step_w), min(h, y1 + step_h)
    crop_path = work_dir / f"agent_crop_{gx}_{gy}.png"
    cv2.imwrite(str(crop_path), img[y1:y2, x1:x2])
    prompt = (
        "List visible component names and nets in this schematic region. "
        'Return JSON: {"components":["..."], "nets":["..."], "connections":[{"source":"","target":""}]}'
    )
    try:
        raw = client.chat_vision(prompt, crop_path)
        data = client.parse_json_response(raw)
        return crop_path, json.dumps(data)[:500]
    except Exception as exc:
        return crop_path, f"crop_inspect_failed: {exc}"


def _slug(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w]+", "_", value.strip().lower()).strip("_")
    return value or fallback
