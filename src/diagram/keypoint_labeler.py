"""NSC auto key-point labeling on circuit/block diagrams."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.diagram.yolo_detector import Detection


def label_keypoints(
    image_path: str | Path,
    detections: list[Detection],
    output_path: str | Path | None = None,
) -> tuple[str, dict[str, tuple[int, int]]]:
    """Label junctions and key connection points; return labeled image path and label map."""
    path = Path(image_path)
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Cannot read image: {path}")

    h, w = img.shape[:2]
    labeled = img.copy()
    label_map: dict[str, tuple[int, int]] = {}
    label_idx = 1

    junctions = [d for d in detections if d.class_name in ("junction", "terminal", "crossover")]
    components = [d for d in detections if d.class_name not in ("junction", "terminal", "crossover")]

    # Label junctions with equipotential groups (same label for nearby junctions on connected lines)
    groups = _cluster_junctions(junctions, threshold=25)
    group_labels: dict[int, str] = {}

    for gi, group in enumerate(groups):
        label = f"J{label_idx}"
        label_idx += 1
        group_labels[gi] = label
        for det in group:
            cx, cy = det.center
            pos = _find_label_position(labeled, cx, cy, det.width, det.height)
            label_map[label] = pos
            _draw_label(labeled, label, pos)

    # Label component centers
    for det in components[:30]:
        cx, cy = det.center
        comp_label = f"C{label_idx}"
        label_idx += 1
        pos = _find_label_position(labeled, cx, cy, det.width, det.height)
        label_map[comp_label] = pos
        _draw_label(labeled, comp_label, pos, color=(0, 128, 255))

    out = Path(output_path) if output_path else path.parent / f"{path.stem}_labeled.png"
    cv2.imwrite(str(out), labeled)
    return str(out), label_map


def _cluster_junctions(junctions: list[Detection], threshold: int) -> list[list[Detection]]:
    if not junctions:
        return []
    groups: list[list[Detection]] = []
    used = [False] * len(junctions)

    for i, j in enumerate(junctions):
        if used[i]:
            continue
        group = [j]
        used[i] = True
        cx, cy = j.center
        for k, other in enumerate(junctions):
            if used[k]:
                continue
            ox, oy = other.center
            if abs(cx - ox) + abs(cy - oy) < threshold:
                group.append(other)
                used[k] = True
        groups.append(group)
    return groups


def _find_label_position(img: np.ndarray, cx: int, cy: int, bw: int, bh: int) -> tuple[int, int]:
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    offsets = [(bw // 2 + 8, 0), (-bw // 2 - 8, 0), (0, bh // 2 + 8), (0, -bh // 2 - 8)]
    for dx, dy in offsets:
        px = min(max(cx + dx, 15), w - 15)
        py = min(max(cy + dy, 15), h - 15)
        x1, y1 = max(0, px - 12), max(0, py - 8)
        x2, y2 = min(w, px + 12), min(h, py + 8)
        region = edges[y1:y2, x1:x2]
        if region.size == 0 or np.count_nonzero(region) < region.size * 0.3:
            return (px, py)
    return (min(max(cx, 15), w - 15), min(max(cy - bh // 2 - 10, 15), h - 15))


def _draw_label(img: np.ndarray, text: str, pos: tuple[int, int], color: tuple[int, int, int] = (0, 0, 255)) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.45
    thickness = 1
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    x, y = pos
    cv2.rectangle(img, (x - 2, y - th - 4), (x + tw + 2, y + 2), (255, 255, 255), -1)
    cv2.putText(img, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)
