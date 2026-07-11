"""YOLO and heuristic detection for diagram key elements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Detection:
    class_name: str
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


def detect_elements(image_path: str | Path, yolo_weights: str | None = None) -> list[Detection]:
    path = Path(image_path)
    if yolo_weights and Path(yolo_weights).exists():
        return _yolo_detect(path, yolo_weights)
    return _heuristic_detect(path)


def _yolo_detect(path: Path, weights: str) -> list[Detection]:
    try:
        from ultralytics import YOLO

        model = YOLO(weights)
        results = model(str(path), verbose=False)
        detections: list[Detection] = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                cls_id = int(box.cls[0])
                name = r.names.get(cls_id, "component")
                conf = float(box.conf[0])
                detections.append(
                    Detection(class_name=name, x1=x1, y1=y1, x2=x2, y2=y2, confidence=conf)
                )
        if detections:
            return detections
    except Exception:
        pass
    return _heuristic_detect(path)


def _heuristic_detect(path: Path) -> list[Detection]:
    img = cv2.imread(str(path))
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    detections: list[Detection] = []

    # Component-like blobs
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        area = cv2.contourArea(c)
        if area < 200 or area > h * w * 0.15:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        aspect = bw / max(bh, 1)
        if 0.1 < aspect < 10 and bw > 15 and bh > 15:
            detections.append(
                Detection(class_name="component", x1=x, y1=y, x2=x + bw, y2=y + bh)
            )

    # Junction detection via line intersections
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40, minLineLength=20, maxLineGap=8)
    if lines is not None:
        junctions = _find_junctions(lines, w, h)
        for jx, jy in junctions[:50]:
            size = 12
            detections.append(
                Detection(
                    class_name="junction",
                    x1=max(0, jx - size),
                    y1=max(0, jy - size),
                    x2=min(w, jx + size),
                    y2=min(h, jy + size),
                )
            )

    return detections


def _find_junctions(lines: np.ndarray, w: int, h: int, grid: int = 15) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        points.extend([(x1, y1), (x2, y2), ((x1 + x2) // 2, (y1 + y2) // 2)])

    clusters: dict[tuple[int, int], int] = {}
    for px, py in points:
        key = (px // grid, py // grid)
        clusters[key] = clusters.get(key, 0) + 1

    junctions: list[tuple[int, int]] = []
    for (gx, gy), count in clusters.items():
        if count >= 3:
            junctions.append((gx * grid + grid // 2, gy * grid + grid // 2))
    return junctions
