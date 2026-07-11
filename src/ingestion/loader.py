"""Unified document loaders for PDF, DOCX, and TXT."""

from __future__ import annotations

import zipfile
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np
from docx import Document as DocxDocument

from src.ingestion.figure_extractor import save_figure_image
from src.ingestion.page_renderer import is_diagram_page, render_pdf_pages
from src.ingestion.section_parser import parse_sections
from src.ingestion.table_extractor import extract_tables_from_pdf
from src.models import DocumentBundle, ExtractedFigure, PageRecord


def _page_line_density(page: fitz.Page) -> float:
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n >= 3:
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        else:
            gray = img[:, :, 0]
        edges = cv2.Canny(gray, 50, 150)
        return float(np.count_nonzero(edges)) / max(edges.size, 1)
    except Exception:
        return 0.0


def _extract_pdf(path: Path, work_dir: Path) -> DocumentBundle:
    doc = fitz.open(path)
    pages_text: list[tuple[int, str]] = []
    full_text_parts: list[str] = []
    embedded_figures: list[ExtractedFigure] = []
    fig_dir = work_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    page_renders_dir = work_dir / "page_renders"
    page_records: list[PageRecord] = []
    diagram_page_nums: list[int] = []
    embedded_by_page: dict[int, int] = {}

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        page = doc[page_idx]
        text = page.get_text("text")
        pages_text.append((page_num, text))
        full_text_parts.append(f"--- Page {page_num} ---\n{text}")

        page_embedded = 0
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                base = doc.extract_image(xref)
                if base["width"] < 40 or base["height"] < 40:
                    continue
                fig = save_figure_image(
                    base["image"],
                    fig_dir,
                    page_num,
                    img_idx,
                )
                fig.source_type = "embedded"
                fig.caption = f"Embedded figure page {page_num}"
                embedded_figures.append(fig)
                page_embedded += 1
            except Exception:
                continue

        embedded_by_page[page_num] = page_embedded
        line_density = _page_line_density(page)
        has_images = page_embedded > 0
        is_diagram = is_diagram_page(text, has_images, line_density)
        if is_diagram:
            diagram_page_nums.append(page_idx)

    doc.close()

    # Render every page at 150 DPI (captures vector block diagrams + UI preview)
    all_page_renders = render_pdf_pages(path, page_renders_dir, dpi=150)
    render_by_page = {f.page: f.path for f in all_page_renders if f.page}

    tables = extract_tables_from_pdf(path)
    tables_by_page: dict[int, int] = {}
    for t in tables:
        tables_by_page[t.page] = tables_by_page.get(t.page, 0) + 1

    for page_num, text in pages_text:
        is_diagram = page_num in [p + 1 for p in diagram_page_nums]
        page_records.append(
            PageRecord(
                page_num=page_num,
                text=text,
                char_count=len(text.strip()),
                table_count=tables_by_page.get(page_num, 0),
                figure_count=embedded_by_page.get(page_num, 0),
                is_diagram_page=is_diagram,
                render_path=render_by_page.get(page_num, ""),
            )
        )

    # Pipeline figures: embedded images + page renders for diagram pages
    figures: list[ExtractedFigure] = list(embedded_figures)
    diagram_page_set = {p + 1 for p in diagram_page_nums}
    for pr in all_page_renders:
        if pr.page in diagram_page_set:
            figures.append(pr)

    # Dedupe by id
    seen_ids: set[str] = set()
    unique_figures: list[ExtractedFigure] = []
    for f in figures:
        if f.id not in seen_ids:
            seen_ids.add(f.id)
            unique_figures.append(f)

    raw_text = "\n\n".join(full_text_parts)
    sections = parse_sections(raw_text, pages_text)
    title = path.stem.replace("_", " ").replace("-", " ").upper()

    return DocumentBundle(
        source_path=str(path),
        format="pdf",
        title=title,
        sections=sections,
        figures=unique_figures,
        tables=tables,
        pages=page_records,
        raw_text=raw_text,
        metadata={
            "page_count": len(pages_text),
            "table_count": len(tables),
            "figure_count": len(unique_figures),
            "diagram_pages": len(diagram_page_nums),
        },
    )


def _extract_docx(path: Path, work_dir: Path) -> DocumentBundle:
    doc = DocxDocument(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    raw_text = "\n\n".join(paragraphs)
    sections = parse_sections(raw_text)

    figures: list[ExtractedFigure] = []
    fig_dir = work_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(path, "r") as zf:
        media_files = [n for n in zf.namelist() if n.startswith("word/media/")]
        for idx, media in enumerate(media_files):
            data = zf.read(media)
            if len(data) < 500:
                continue
            fig = save_figure_image(data, fig_dir, page=0, index=idx)
            figures.append(fig)

    title = path.stem.replace("_", " ").replace("-", " ").title()
    return DocumentBundle(
        source_path=str(path),
        format="docx",
        title=title,
        sections=sections,
        figures=figures,
        tables=[],
        pages=[],
        raw_text=raw_text,
        metadata={"paragraph_count": len(paragraphs)},
    )


def _extract_txt(path: Path, work_dir: Path) -> DocumentBundle:
    raw_text = path.read_text(encoding="utf-8", errors="replace")
    sections = parse_sections(raw_text)
    title = path.stem.replace("_", " ").replace("-", " ").title()
    return DocumentBundle(
        source_path=str(path),
        format="txt",
        title=title,
        sections=sections,
        figures=[],
        tables=[],
        pages=[],
        raw_text=raw_text,
        metadata={},
    )


def load_document(path: str | Path, work_dir: str | Path | None = None) -> DocumentBundle:
    """Load a hardware specification from PDF, DOCX, or TXT."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    base_work = Path(work_dir) if work_dir else path.parent / ".spec_work"
    base_work.mkdir(parents=True, exist_ok=True)
    session_dir = base_work / path.stem
    session_dir.mkdir(parents=True, exist_ok=True)

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path, session_dir)
    if suffix in (".docx", ".doc"):
        if suffix == ".doc":
            raise ValueError("Legacy .doc format not supported; convert to .docx or PDF")
        return _extract_docx(path, session_dir)
    if suffix in (".txt", ".md"):
        return _extract_txt(path, session_dir)

    raise ValueError(f"Unsupported format: {suffix}. Use PDF, DOCX, or TXT.")
