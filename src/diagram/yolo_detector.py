"""YOLO and heuristic detection for diagram key elements."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEIGHTS = ROOT / "models" / "schematic_yolov8.pt"
FALLBACK_WEIGHTS = ROOT / "models" / "schematic_yolov8_nano.pt"

# Circuit-schematic classes (AITEE / CKnievel/aitee-dataset YOLOv8 weights)
MIN_CONFIDENCE = 0.55
MAX_DETECTIONS = 30
LABEL_NOISE_CLASSES = {
    "current_label",
    "current_label_dir",
    "resistor_label",
    "voltage_label",
    "voltage_label_dir",
}

SCHEMATIC_CLASS_ALIASES = {
    "E": "edge",
    "GND": "ground",
    "I": "current_source",
    "p": "probe",
    "R": "resistor",
    "V": "voltage_source",
    "ident-i": "current_label",
    "ident-i-dir": "current_label_dir",
    "ident-res": "resistor_label",
    "ident-v": "voltage_label",
    "ident-v-dir": "voltage_label_dir",
}


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


def resolve_yolo_weights(yolo_weights: str | None = None) -> str | None:
    """Return path to schematic YOLO weights if available."""
    if yolo_weights:
        path = Path(yolo_weights)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            return str(path)

    if DEFAULT_WEIGHTS.exists():
        return str(DEFAULT_WEIGHTS.resolve())
    if FALLBACK_WEIGHTS.exists():
        return str(FALLBACK_WEIGHTS)
    return None


def detect_elements(
    image_path: str | Path,
    yolo_weights: str | None = None,
    *,
    max_detections: int = MAX_DETECTIONS,
) -> list[Detection]:
    path = Path(image_path)
    resolved = resolve_yolo_weights(yolo_weights)
    if resolved:
        detections = _yolo_detect(path, resolved, max_detections=max_detections)
        if detections:
            return detections
    return _heuristic_detect(path, max_detections=max_detections)


def _normalize_class_name(name: str) -> str:
    return SCHEMATIC_CLASS_ALIASES.get(name, name)


def _yolo_detect(path: Path, weights: str, *, max_detections: int = MAX_DETECTIONS) -> list[Detection]:
    try:
        from ultralytics import YOLO

        # CPU inference avoids GPU memory contention with Ollama on the same machine.
        device = os.environ.get("YOLO_DEVICE", "cpu")
        model = YOLO(weights)
        results = model(str(path), verbose=False, device=device)
        detections: list[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                cls_id = int(box.cls[0])
                raw_name = r.names.get(cls_id, "component")
                name = _normalize_class_name(str(raw_name))
                conf = float(box.conf[0])
                if conf < MIN_CONFIDENCE:
                    continue
                if name in LABEL_NOISE_CLASSES:
                    continue
                kind = "junction" if name in {"edge", "probe"} else "component"
                detections.append(
                    Detection(class_name=kind if kind == "junction" else name, x1=x1, y1=y1, x2=x2, y2=y2, confidence=conf)
                )
        if detections:
            detections.sort(key=lambda d: d.confidence, reverse=True)
            return detections[:max_detections]
    except Exception:
        pass
    return _heuristic_detect(path, max_detections=max_detections)


def _heuristic_detect(path: Path, *, max_detections: int = MAX_DETECTIONS) -> list[Detection]:
    img = cv2.imread(str(path))
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    detections: list[Detection] = []

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

    return detections[:max_detections]


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
