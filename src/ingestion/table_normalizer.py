"""Normalize extracted datasheet tables into structured parameter rows."""

from __future__ import annotations

import re

from src.models import DocumentBundle, ExtractedTable, NormalizedParameterRow

UNIT_ALIASES = {
    "ua": "uA",
    "µa": "uA",
    "µA": "uA",
    "microampere": "uA",
    "microamp": "uA",
    "uv": "uV",
    "µv": "uV",
    "µV": "uV",
    "mv": "mV",
    "kv": "kV",
    "khz": "kHz",
    "mhz": "MHz",
    "ppm": "ppm",
    "c": "C",
    "°c": "C",
    "degc": "C",
}


def normalize_unit(unit: str) -> tuple[str, str]:
    raw = unit.strip()
    if not raw:
        return "", ""
    key = raw.lower().replace("°", "")
    canonical = UNIT_ALIASES.get(key, raw)
    return canonical, raw


def _header_index(header: list[str], candidates: tuple[str, ...]) -> int | None:
    joined = [h.lower().strip() for h in header]
    for i, col in enumerate(joined):
        if any(c in col for c in candidates):
            return i
    return None


def _is_parameter_table(header: list[str]) -> bool:
    joined = " ".join(h.lower() for h in header)
    return any(k in joined for k in ("parameter", "symbol", "min", "typ", "max", "unit", "conditions"))


def normalize_table(table: ExtractedTable, section: str = "") -> list[NormalizedParameterRow]:
    if not table.rows or len(table.rows) < 2:
        return []

    header = [str(c or "").strip() for c in table.rows[0]]
    if not _is_parameter_table(header):
        return []

    idx_param = _header_index(header, ("parameter",))
    idx_symbol = _header_index(header, ("symbol",))
    idx_cond = _header_index(header, ("condition",))
    idx_min = _header_index(header, ("min",))
    idx_typ = _header_index(header, ("typ",))
    idx_max = _header_index(header, ("max",))
    idx_unit = _header_index(header, ("unit",))

    rows: list[NormalizedParameterRow] = []
    carry_conditions = ""

    for row in table.rows[1:]:
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue

        def cell_at(idx: int | None) -> str:
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx]

        parameter = cell_at(idx_param) or (cells[0] if cells else "")
        symbol = cell_at(idx_symbol)
        conditions = cell_at(idx_cond)
        if conditions:
            carry_conditions = conditions
        elif carry_conditions and not parameter:
            conditions = carry_conditions
        minimum = cell_at(idx_min)
        typical = cell_at(idx_typ)
        maximum = cell_at(idx_max)
        unit_raw = cell_at(idx_unit)
        unit, original_unit = normalize_unit(unit_raw)

        if not parameter and not symbol:
            continue

        rows.append(
            NormalizedParameterRow(
                parameter=parameter,
                symbol=symbol,
                conditions=conditions,
                minimum=minimum,
                typical=typical,
                maximum=maximum,
                unit=unit,
                original_unit=original_unit,
                source_pdf_page=table.page,
                section=section,
            )
        )

    return rows


def normalize_document_tables(document: DocumentBundle) -> list[NormalizedParameterRow]:
    all_rows: list[NormalizedParameterRow] = []
    for table in document.tables:
        section = _infer_section(document, table.page)
        all_rows.extend(normalize_table(table, section=section))
    return all_rows


def _infer_section(document: DocumentBundle, page: int) -> str:
    for section in document.sections:
        if section.page_start and section.page_start <= page <= (section.page_end or section.page_start):
            return section.title
    page_text = next((p.text for p in document.pages if p.page_num == page), "")
    for label in (
        "Electrical Characteristics",
        "Absolute Maximum Ratings",
        "Recommended Operating Conditions",
        "Battery-Supply Electrical Characteristics",
    ):
        if re.search(re.escape(label), page_text, re.IGNORECASE):
            return label
    return ""
