"""OCR extraction for schematic text (PaddleOCR with fallbacks)."""

from __future__ import annotations

import re
from pathlib import Path

import cv2

from src.models import BoundingBox, TextInstance


def extract_text_instances(image_path: str | Path) -> list[TextInstance]:
    path = Path(image_path)
    texts = _paddle_ocr(path)
    if texts:
        return texts
    return _tesseract_ocr(path)


def ocr_region(image_path: str | Path, bbox: BoundingBox) -> TextInstance | None:
    path = Path(image_path)
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    x1, y1 = max(0, bbox.x1), max(0, bbox.y1)
    x2, y2 = min(w, bbox.x2), min(h, bbox.y2)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    tmp = path.parent / f".ocr_{path.stem}_{x1}_{y1}.png"
    try:
        cv2.imwrite(str(tmp), crop)
        hits = extract_text_instances(tmp)
        if not hits:
            return None
        text = " ".join(t.text for t in hits).strip()
        if not text:
            return None
        return TextInstance(text=text, bbox=bbox, confidence=hits[0].confidence, source=hits[0].source)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _paddle_ocr(path: Path) -> list[TextInstance]:
    try:
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = ocr.ocr(str(path), cls=True)
        texts: list[TextInstance] = []
        for block in result or []:
            for line in block or []:
                if not line or len(line) < 2:
                    continue
                box, payload = line[0], line[1]
                content = str(payload[0]).strip()
                conf = float(payload[1]) if len(payload) > 1 else 0.5
                if not content or conf < 0.35:
                    continue
                xs = [int(p[0]) for p in box]
                ys = [int(p[1]) for p in box]
                texts.append(
                    TextInstance(
                        text=_clean_text(content),
                        bbox=BoundingBox(x1=min(xs), y1=min(ys), x2=max(xs), y2=max(ys)),
                        confidence=conf,
                        source="paddleocr",
                    )
                )
        return _dedupe_texts(texts)
    except Exception:
        return []


def _tesseract_ocr(path: Path) -> list[TextInstance]:
    try:
        import pytesseract
        from pytesseract import Output

        img = cv2.imread(str(path))
        if img is None:
            return []
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
        texts: list[TextInstance] = []
        n = len(data.get("text", []))
        for i in range(n):
            content = str(data["text"][i]).strip()
            conf = float(data["conf"][i]) if data["conf"][i] not in ("-1", -1) else 0.0
            if not content or conf < 35:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            texts.append(
                TextInstance(
                    text=_clean_text(content),
                    bbox=BoundingBox(x1=x, y1=y, x2=x + w, y2=y + h),
                    confidence=conf / 100.0,
                    source="tesseract",
                )
            )
        return _dedupe_texts(texts)
    except Exception:
        return []


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text


def _dedupe_texts(texts: list[TextInstance]) -> list[TextInstance]:
    seen: set[str] = set()
    out: list[TextInstance] = []
    for item in sorted(texts, key=lambda t: -t.confidence):
        key = f"{item.text.lower()}|{item.bbox.x1}|{item.bbox.y1}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
