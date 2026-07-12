"""Build OmniSch-style spatial netlists from detections + OCR + geometry."""

from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np

from src.diagram.ocr_extractor import extract_text_instances, ocr_region
from src.diagram.yolo_detector import Detection, detect_elements
from src.models import BoundingBox, DiagramType, NetEdge, SpatialNetlist, SymbolInstance, TextInstance

MAX_NETS = 40
MAX_SYMBOLS = 25
MAX_HOUGH_CLUSTERS = 12


def _slug(value: str) -> str:
    value = re.sub(r"[^\w]+", "_", value.strip().lower()).strip("_")
    return value or "node"


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bbox_from_detection(det: Detection) -> BoundingBox:
    return BoundingBox(x1=det.x1, y1=det.y1, x2=det.x2, y2=det.y2)


def _nearest_symbol(
    point: tuple[float, float],
    symbols: list[SymbolInstance],
    max_dist: float,
) -> SymbolInstance | None:
    best: SymbolInstance | None = None
    best_d = max_dist
    for sym in symbols:
        d = _distance(point, sym.bbox.center)
        if d < best_d:
            best_d = d
            best = sym
    return best


def _label_for_detection(
    det: Detection,
    image_path: Path,
    texts: list[TextInstance],
    index: int,
) -> str:
    center = det.center
    for text in texts:
        cx, cy = text.bbox.center
        if text.bbox.x1 <= center[0] <= text.bbox.x2 and text.bbox.y1 <= center[1] <= text.bbox.y2:
            return text.text
        if _distance(center, (cx, cy)) < max(det.width, det.height) * 0.8:
            return text.text

    hit = ocr_region(image_path, _bbox_from_detection(det))
    if hit and hit.text:
        return hit.text

    if det.class_name == "junction":
        return f"J{index + 1}"
    return f"{det.class_name}_{index + 1}"


def build_spatial_netlist(
    figure_id: str,
    image_path: str | Path,
    page: int = 0,
    yolo_weights: str | None = None,
    extra_nets: list[NetEdge] | None = None,
    diagram_type: DiagramType | None = None,
) -> SpatialNetlist:
    path = Path(image_path)
    use_yolo = diagram_type not in (DiagramType.BLOCK_DIAGRAM,)
    max_detections = 20 if diagram_type == DiagramType.BLOCK_DIAGRAM else 30
    detections = detect_elements(
        path,
        yolo_weights=yolo_weights if use_yolo else None,
        max_detections=max_detections,
    )
    texts = extract_text_instances(path)

    symbols: list[SymbolInstance] = []
    junctions: list[SymbolInstance] = []
    for i, det in enumerate(detections):
        name = _label_for_detection(det, path, texts, i)
        sym = SymbolInstance(
            id=_slug(name) if det.class_name != "junction" else f"j{i + 1}",
            name=name,
            symbol_type="junction" if det.class_name == "junction" else "component",
            bbox=_bbox_from_detection(det),
            confidence=det.confidence,
        )
        if sym.symbol_type == "junction":
            junctions.append(sym)
        else:
            symbols.append(sym)
        if len(symbols) >= MAX_SYMBOLS:
            break

    for i, text in enumerate(texts):
        if len(text.text) > 40:
            continue
        if any(_distance(text.bbox.center, s.bbox.center) < 20 for s in symbols):
            continue
        symbols.append(
            SymbolInstance(
                id=_slug(text.text) or f"text_{i}",
                name=text.text,
                symbol_type="text_anchor",
                bbox=text.bbox,
                confidence=text.confidence,
            )
        )

    nets = _infer_nets_from_geometry(path, symbols, junctions, diagram_type=diagram_type)
    if extra_nets:
        nets.extend(extra_nets[:10])
    nets = _dedupe_nets(nets)[:MAX_NETS]

    confidence = min(0.95, 0.35 + 0.05 * len(symbols) + 0.03 * len(nets))
    return SpatialNetlist(
        figure_id=figure_id,
        page=page,
        symbols=symbols + junctions,
        texts=texts,
        nets=nets,
        confidence=round(confidence, 2),
        pipeline="omnish",
    )


def _infer_nets_from_geometry(
    image_path: Path,
    symbols: list[SymbolInstance],
    junctions: list[SymbolInstance],
    diagram_type: DiagramType | None = None,
) -> list[NetEdge]:
    nets: list[NetEdge] = []
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return _pairwise_fallback(symbols)

    h, w = img.shape
    edges = cv2.Canny(img, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=35, minLineLength=25, maxLineGap=10)
    if lines is None:
        return _pairwise_fallback(symbols)

    anchors = symbols + junctions
    if len(anchors) < 2:
        return nets

    line_points: list[tuple[int, int]] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        line_points.extend([(x1, y1), (x2, y2), ((x1 + x2) // 2, (y1 + y2) // 2)])

    clusters: dict[tuple[int, int], list[tuple[int, int]]] = {}
    grid = 18
    for px, py in line_points:
        key = (px // grid, py // grid)
        clusters.setdefault(key, []).append((px, py))

    max_clusters = MAX_HOUGH_CLUSTERS if diagram_type == DiagramType.BLOCK_DIAGRAM else 20
    ranked_clusters = sorted(clusters.items(), key=lambda item: len(item[1]), reverse=True)
    for (gx, gy), pts in ranked_clusters[:max_clusters]:
        if len(pts) < 2:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        nearby = sorted(
            anchors,
            key=lambda s: _distance((cx, cy), s.bbox.center),
        )[:3]
        for i in range(len(nearby) - 1):
            a, b = nearby[i], nearby[i + 1]
            weight = 1.0 - min(1.0, _distance(a.bbox.center, b.bbox.center) / max(w, h))
            nets.append(
                NetEdge(
                    source_id=a.id,
                    target_id=b.id,
                    net_name=f"net_{gx}_{gy}",
                    relationship="spatial_connect",
                    spatial_weight=round(max(0.2, weight), 2),
                    evidence="hough_line_cluster",
                )
            )

    for sym in symbols:
        nearest_j = _nearest_symbol(sym.bbox.center, junctions, max_dist=max(w, h) * 0.08)
        if nearest_j:
            nets.append(
                NetEdge(
                    source_id=sym.id,
                    target_id=nearest_j.id,
                    net_name=nearest_j.name,
                    relationship="connects",
                    spatial_weight=0.7,
                    evidence="nearest_junction",
                )
            )

    if not nets:
        return _pairwise_fallback(symbols)
    return nets


def _pairwise_fallback(symbols: list[SymbolInstance]) -> list[NetEdge]:
    comps = [s for s in symbols if s.symbol_type == "component"]
    nets: list[NetEdge] = []
    for i in range(len(comps) - 1):
        nets.append(
            NetEdge(
                source_id=comps[i].id,
                target_id=comps[i + 1].id,
                relationship="inferred_sequence",
                spatial_weight=0.4,
                evidence="symbol_proximity_fallback",
            )
        )
    return nets


def _dedupe_nets(nets: list[NetEdge]) -> list[NetEdge]:
    seen: set[str] = set()
    out: list[NetEdge] = []
    for net in nets:
        key = f"{net.source_id}|{net.target_id}|{net.net_name}"
        rev = f"{net.target_id}|{net.source_id}|{net.net_name}"
        if key in seen or rev in seen:
            continue
        seen.add(key)
        out.append(net)
    return out


def merge_spatial_netlists(netlists: list[SpatialNetlist], *, max_symbols: int = 30, max_nets: int = 50) -> SpatialNetlist:
    if not netlists:
        return SpatialNetlist()
    merged = SpatialNetlist(
        figure_id="merged_spatial_netlist",
        page=netlists[0].page,
        confidence=max(n.confidence for n in netlists),
        pipeline="omnish",
    )
    seen_sym: set[str] = set()
    seen_net: set[str] = set()
    for nl in netlists:
        for sym in nl.symbols:
            if sym.id not in seen_sym:
                merged.symbols.append(sym)
                seen_sym.add(sym.id)
                if len(merged.symbols) >= max_symbols:
                    break
        merged.texts.extend(nl.texts)
        for net in nl.nets:
            key = f"{net.source_id}|{net.target_id}|{net.relationship}"
            if key not in seen_net:
                merged.nets.append(net)
                seen_net.add(key)
                if len(merged.nets) >= max_nets:
                    break
        if len(merged.symbols) >= max_symbols and len(merged.nets) >= max_nets:
            break
    return merged
