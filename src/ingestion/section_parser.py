"""Section parsing from raw document text."""

from __future__ import annotations

import re

from src.models import SectionChunk


HEADING_PATTERNS = [
    re.compile(r"^(?P<title>(?:\d+\.)+\s*.+)$", re.MULTILINE),
    re.compile(r"^(?P<title>(?:Chapter|Section|Appendix)\s+[\dA-Z.]+[:\s].+)$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^(?P<title>#{1,6}\s+.+)$", re.MULTILINE),
]


def _heading_level(title: str) -> int:
    if title.startswith("#"):
        return len(title) - len(title.lstrip("#"))
    dot_count = title.split()[0].count(".") if title.split() else 1
    return min(max(dot_count, 1), 6)


def _clean_title(title: str) -> str:
    title = title.strip()
    if title.startswith("#"):
        title = title.lstrip("#").strip()
    return title


def parse_sections(text: str, pages: list[tuple[int, str]] | None = None) -> list[SectionChunk]:
    """Split document text into hierarchical sections."""
    if not text.strip():
        return [SectionChunk(id="sec_0", title="Document", level=1, content="")]

    headings: list[tuple[int, str, int]] = []
    for pattern in HEADING_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group("title")
            title = _clean_title(raw)
            if len(title) < 3 or title.isdigit():
                continue
            pos = match.start()
            level = _heading_level(raw)
            headings.append((pos, title, level))

    headings.sort(key=lambda x: x[0])
    deduped: list[tuple[int, str, int]] = []
    seen_pos: set[int] = set()
    for pos, title, level in headings:
        if pos in seen_pos:
            continue
        seen_pos.add(pos)
        deduped.append((pos, title, level))
    headings = deduped

    if not headings:
        return [SectionChunk(id="sec_0", title="Document", level=1, content=text.strip())]

    sections: list[SectionChunk] = []
    for i, (pos, title, level) in enumerate(headings):
        end = headings[i + 1][0] if i + 1 < len(headings) else len(text)
        content = text[pos:end].strip()
        content = re.sub(r"^" + re.escape(title) + r"\s*", "", content, count=1).strip()

        page_start = None
        if pages:
            char_count = 0
            for page_num, page_text in pages:
                char_count += len(page_text) + 1
                if char_count > pos:
                    page_start = page_num
                    break

        fig_refs = re.findall(r"(?:Figure|Fig\.?|Table)\s+[\d.]+", content, re.IGNORECASE)
        sections.append(
            SectionChunk(
                id=f"sec_{i}",
                title=title,
                level=level,
                content=content,
                page_start=page_start,
                figure_refs=list(dict.fromkeys(fig_refs)),
            )
        )

    return sections
