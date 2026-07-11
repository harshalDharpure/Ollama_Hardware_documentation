"""Extract tables from PDF pages using pdfplumber."""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from src.models import ExtractedTable


def _table_to_markdown(rows: list[list[str | None]]) -> str:
    if not rows:
        return ""
    cleaned: list[list[str]] = []
    for row in rows:
        cleaned.append([str(c or "").strip().replace("\n", " ") for c in row])
    if not cleaned:
        return ""

    max_cols = max(len(r) for r in cleaned)
    for row in cleaned:
        while len(row) < max_cols:
            row.append("")

    header = cleaned[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * max_cols) + " |",
    ]
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def extract_tables_from_pdf(path: Path) -> list[ExtractedTable]:
    tables: list[ExtractedTable] = []
    table_idx = 0

    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                page_tables = page.extract_tables() or []
            except Exception:
                page_tables = []

            for ti, raw in enumerate(page_tables):
                if not raw or len(raw) < 1:
                    continue
                non_empty = sum(1 for row in raw if any(str(c or "").strip() for c in row))
                if non_empty < 2:
                    continue

                table_idx += 1
                tid = f"table_{page_num}_{ti}"
                md = _table_to_markdown(raw)
                rows_clean = [
                    [str(c or "").strip() for c in row]
                    for row in raw
                    if any(str(c or "").strip() for c in row)
                ]
                tables.append(
                    ExtractedTable(
                        id=tid,
                        page=page_num,
                        markdown=md,
                        rows=rows_clean,
                        row_count=len(rows_clean),
                        col_count=max(len(r) for r in rows_clean) if rows_clean else 0,
                        caption=f"Table on page {page_num}",
                    )
                )

    return tables
