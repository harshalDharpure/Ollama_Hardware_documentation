"""Diagram type classification."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from src.models import DiagramType, ExtractedFigure


def classify_diagram(figure: ExtractedFigure, dense_threshold: int = 40) -> DiagramType:
    path = Path(figure.path)
    if not path.exists():
        return DiagramType.OTHER

    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return DiagramType.OTHER

    h, w = img.shape
    if h < 50 or w < 50:
        return DiagramType.OTHER

    edges = cv2.Canny(img, 50, 150)
    line_density = np.count_nonzero(edges) / (h * w)

    _, binary = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    symbol_count = sum(1 for c in contours if 100 < cv2.contourArea(c) < h * w * 0.05)

    if symbol_count > dense_threshold or (symbol_count > 25 and line_density > 0.08):
        return DiagramType.DENSE_COMPLEX
    if line_density > 0.04 and symbol_count > 3:
        return DiagramType.SCHEMATIC
    if line_density > 0.02:
        return DiagramType.BLOCK_DIAGRAM
    return DiagramType.OTHER
