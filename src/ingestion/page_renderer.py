"""Render PDF pages to high-DPI images for diagram extraction."""

from __future__ import annotations

from pathlib import Path

import fitz

from src.models import ExtractedFigure


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = 150,
    pages: list[int] | None = None,
) -> list[ExtractedFigure]:
    """Render each PDF page as PNG (captures vector block diagrams)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    figures: list[ExtractedFigure] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    page_indices = pages if pages is not None else range(len(doc))
    for page_idx in page_indices:
        if page_idx < 0 or page_idx >= len(doc):
            continue
        page_num = page_idx + 1
        page = doc[page_idx]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        fig_id = f"page_{page_num}"
        out_path = output_dir / f"{fig_id}.png"
        pix.save(str(out_path))
        figures.append(
            ExtractedFigure(
                id=fig_id,
                path=str(out_path),
                page=page_num,
                caption=f"Page {page_num} render",
                section_ref=f"Page {page_num}",
                width=pix.width,
                height=pix.height,
                source_type="page_render",
            )
        )

    doc.close()
    return figures


def is_diagram_page(text: str, has_embedded_images: bool, line_density: float) -> bool:
    """Heuristic: page likely contains block/timing diagram."""
    text_len = len(text.strip())
    if has_embedded_images:
        return True
    if line_density > 0.035 and text_len < 2500:
        return True
    if line_density > 0.06:
        return True
    diagram_keywords = (
        "figure", "fig.", "diagram", "timing", "block diagram",
        "functional", "pin configuration", "typical operating",
    )
    lower = text.lower()
    if any(k in lower for k in diagram_keywords) and line_density > 0.02:
        return True
    return False
