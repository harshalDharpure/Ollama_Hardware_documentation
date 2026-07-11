"""Hough transform and equipotential label refinement (NSC step 3-4)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.diagram.yolo_detector import Detection


def refine_equipotential_labels(
    image_path: str | Path,
    detections: list[Detection],
    label_map: dict[str, tuple[int, int]],
) -> dict[str, str]:
    """
    Identify equipotential junction groups via Hough line connectivity.
    Returns mapping from label -> equipotential group label.
    """
    path = Path(image_path)
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {k: k for k in label_map}

    h, w = img.shape
    edges = cv2.Canny(img, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=35, minLineLength=25, maxLineGap=10)

    junction_dets = [d for d in detections if d.class_name == "junction"]
    if lines is None or not junction_dets:
        return {k: k for k in label_map if k.startswith("J")}

    # Build adjacency between junctions connected by lines without components between
    comp_mask = _component_mask(img.shape, detections)
    adj: dict[int, set[int]] = {i: set() for i in range(len(junction_dets))}

    for i, j1 in enumerate(junction_dets):
        for j, j2 in enumerate(junction_dets):
            if i >= j:
                continue
            if _connected_by_line(j1, j2, lines, comp_mask):
                adj[i].add(j)
                adj[j].add(i)

    # Union-find for equipotential groups
    parent = list(range(len(junction_dets)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, neighbors in adj.items():
        for j in neighbors:
            union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(junction_dets)):
        root = find(i)
        groups.setdefault(root, []).append(i)

    j_labels = [k for k in sorted(label_map.keys()) if k.startswith("J")]
    refined: dict[str, str] = {}
    for gi, (_, members) in enumerate(groups.items()):
        group_label = f"J{gi + 1}"
        for mi, idx in enumerate(members):
            if idx < len(j_labels):
                refined[j_labels[idx]] = group_label

    for k in label_map:
        if k not in refined:
            refined[k] = k
    return refined


def draw_connectivity_overlay(
    image_path: str | Path,
    detections: list[Detection],
    output_path: str | Path,
) -> str:
    """Visualize detected lines on diagram."""
    path = Path(image_path)
    img = cv2.imread(str(path))
    if img is None:
        return str(path)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=35, minLineLength=25, maxLineGap=10)
    overlay = img.copy()
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            cv2.line(overlay, (x1, y1), (x2, y2), (0, 255, 0), 1)

    out = Path(output_path)
    cv2.imwrite(str(out), overlay)
    return str(out)


def _component_mask(shape: tuple[int, ...], detections: list[Detection]) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for d in detections:
        if d.class_name == "component":
            cv2.rectangle(mask, (d.x1, d.y1), (d.x2, d.y2), 255, -1)
    return mask


def _connected_by_line(j1: Detection, j2: Detection, lines: np.ndarray, comp_mask: np.ndarray) -> bool:
    cx1, cy1 = j1.center
    cx2, cy2 = j2.center
    dist = abs(cx1 - cx2) + abs(cy1 - cy2)
    if dist > 120:
        return False

    for line in lines:
        x1, y1, x2, y2 = line[0]
        if _point_near_line(cx1, cy1, x1, y1, x2, y2, 12) and _point_near_line(cx2, cy2, x1, y1, x2, y2, 12):
            mid_x, mid_y = (cx1 + cx2) // 2, (cy1 + cy2) // 2
            if comp_mask[mid_y, mid_x] == 0:
                return True
    return False


def _point_near_line(px: int, py: int, x1: int, y1: int, x2: int, y2: int, tol: int) -> bool:
    num = abs((y2 - y1) * px - (x2 - x1) * py + x2 * y1 - y2 * x1)
    den = max(((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5, 1)
    return num / den < tol
