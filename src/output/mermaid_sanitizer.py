"""Sanitize and validate Mermaid diagram code for rendering."""

from __future__ import annotations

import re


_MERMAID_STARTERS = ("graph ", "flowchart ", "sequencediagram", "classdiagram", "statediagram")
_HEADER_RE = re.compile(
    r"^(flowchart\s+(?:LR|RL|TB|BT|TD)|graph\s+(?:TD|LR|TB|RL|BT))\b",
    re.IGNORECASE,
)
_ARROW_PATTERN = r"(?:-->|<-->|---|<--|==>|-\.->)"
_EDGE_RE = re.compile(
    rf"^([A-Za-z_][\w]*)\s*{_ARROW_PATTERN}\s*(.+)$"
)
_EDGE_LABEL_RE = re.compile(
    rf"^([A-Za-z_][\w]*)\s*{_ARROW_PATTERN}\s*\|([^|]+)\|\s*([A-Za-z_][\w]*)$"
)


def sanitize_mermaid(code: str) -> str:
    """Return render-safe Mermaid code."""
    if not code or not code.strip():
        return 'graph TD\n    Empty["No diagram available"]'

    text = _extract_mermaid_body(code.strip())
    text = _repair_llm_relationship_edges(text)
    text = _expand_collapsed_diagram(text)
    text = re.sub(r";\s*", "\n", text)

    kept: list[str] = []
    for raw_line in text.splitlines():
        line = _normalize_arrow_spacing(raw_line.strip())
        if not line:
            continue

        header_match = _HEADER_RE.match(line)
        if header_match and not kept:
            kept.append(_normalize_header(header_match.group(1)))
            continue

        if not _looks_like_mermaid_line(line):
            continue
        kept.append(_sanitize_line(line))

    if not kept:
        return 'graph TD\n    Empty["Diagram syntax could not be parsed"]'

    kept = _ensure_diagram_header(kept)
    merged = _dedupe_node_defs("\n".join(kept))
    return cap_mermaid_edges(merged, max_edges=80)


def count_mermaid_edges(code: str) -> int:
    """Count edge lines in Mermaid source."""
    if not code or not code.strip():
        return 0
    text = _extract_mermaid_body(code.strip())
    count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _HEADER_RE.match(line) or line.startswith("subgraph") or line == "end":
            continue
        if _EDGE_RE.match(line) or _EDGE_LABEL_RE.match(line):
            count += 1
        elif "-->" in line or "---" in line or "<--" in line or "==>" in line:
            count += 1
    return count


def cap_mermaid_edges(code: str, max_edges: int = 80) -> str:
    """Truncate excess edges so Mermaid stays within renderer limits."""
    if not code or count_mermaid_edges(code) <= max_edges:
        return code

    text = _extract_mermaid_body(code.strip())
    out: list[str] = []
    edge_count = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _HEADER_RE.match(line) or line.startswith("subgraph") or line == "end":
            out.append(raw_line.rstrip())
            continue
        is_edge = (
            _EDGE_RE.match(line)
            or _EDGE_LABEL_RE.match(line)
            or "-->" in line
            or "---" in line
            or "<--" in line
            or "==>" in line
        )
        if is_edge:
            if edge_count >= max_edges:
                continue
            edge_count += 1
        out.append(raw_line.rstrip())
    return "\n".join(out)


def is_valid_mermaid(code: str) -> bool:
    """Return True when raw code is likely renderable by Mermaid."""
    if not code or not code.strip():
        return False

    text = _extract_mermaid_body(code.strip())
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    if not any(_HEADER_RE.match(line) for line in lines):
        return False
    if "__" in text and "|" not in text:
        return False

    sanitized = sanitize_mermaid(code)
    if "Empty[" in sanitized or "Unavailable[" in sanitized:
        return False
    sanitized_lines = [line.strip() for line in sanitized.splitlines() if line.strip()]
    return len(sanitized_lines) >= 2


def _extract_mermaid_body(text: str) -> str:
    if "```" in text:
        match = re.search(r"```(?:mermaid)?\s*([\s\S]*?)```", text)
        if match:
            return match.group(1).strip()
    return text


def _repair_llm_relationship_edges(text: str) -> str:
    """Convert `A --> powers__power_control` into labeled edges."""
    repaired: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _HEADER_RE.match(line):
            repaired.append(line)
            continue
        match = re.match(rf"^([A-Za-z_][\w]*)\s*({_ARROW_PATTERN})\s*(.+)$", line)
        if not match:
            repaired.append(line)
            continue
        src, arrow, dst = match.group(1), match.group(2), match.group(3).strip()
        if "|" in line or "__" not in dst:
            repaired.append(line)
            continue
        rel, target = dst.rsplit("__", 1)
        if rel and target:
            repaired.append(f'{src} {arrow}|"{_escape_label(rel)}"| {target}')
        else:
            repaired.append(line)
    return "\n".join(repaired)


def _normalize_arrow_spacing(line: str) -> str:
    line = re.sub(rf"(\w)({_ARROW_PATTERN})", r"\1 \2", line)
    line = re.sub(rf"({_ARROW_PATTERN})(\w)", r"\1 \2", line)
    return line.strip()


def _split_inline_body(chunk: str) -> list[str]:
    chunk = _normalize_arrow_spacing(chunk)
    chunk = re.sub(r"\s+([A-Za-z_][\w]*)(\[[^\]]+\])", r"\n\1\2", chunk)
    chunk = re.sub(r"\s+([A-Za-z_][\w]*)(\([^)]+\))", r"\n\1\2", chunk)
    chunk = re.sub(
        rf"\s+([A-Za-z_][\w]*)\s*({_ARROW_PATTERN})\s*([^\n]+)",
        r"\n\1 \2 \3",
        chunk,
    )
    return [part.strip() for part in chunk.split("\n") if part.strip()]


def _expand_collapsed_diagram(text: str) -> str:
    """Break single-line LLM output into one statement per line."""
    if not text:
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.count("\n") > 3:
        return text

    header_match = _HEADER_RE.match(text)
    if header_match:
        header = header_match.group(1).strip()
        body = text[len(header_match.group(0)) :].strip()
        text = f"{header}\n{body}" if body else header

    text = re.sub(r"\s+subgraph\s+", "\nsubgraph ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+end\b", "\nend", text, flags=re.IGNORECASE)

    expanded_parts: list[str] = []
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.lower().startswith("subgraph "):
            match = re.match(
                r"(subgraph\s+[A-Za-z_][\w]*(?:\[[^\]]+\])?)(?:\s+(.*))?$",
                chunk,
                flags=re.IGNORECASE,
            )
            if match:
                expanded_parts.append(match.group(1).strip())
                if match.group(2):
                    expanded_parts.extend(_split_inline_body(match.group(2)))
                continue
        expanded_parts.extend(_split_inline_body(chunk))

    return "\n".join(expanded_parts)


def _ensure_diagram_header(lines: list[str]) -> list[str]:
    if lines and _HEADER_RE.match(lines[0]):
        return lines
    has_flow = any("flowchart" in line.lower() or "subgraph" in line.lower() for line in lines)
    has_graph = any(line.lower().startswith("graph ") for line in lines)
    header = "flowchart LR" if has_flow or not has_graph else "graph TD"
    return [header, *lines]


def _sanitize_line(line: str) -> str:
    line = line.strip().rstrip(";")
    if line.lower().startswith("subgraph "):
        return _quote_labels(line)
    if _EDGE_LABEL_RE.match(line):
        return _quote_labels(line)
    line = _fix_spaced_edge_targets(line)
    line = _fix_relationship_node_labels(line)
    line = _fix_node_ids(line)
    return _quote_labels(line)


def _normalize_header(line: str) -> str:
    line = line.strip().rstrip(";")
    if line.lower().startswith("graph"):
        parts = line.split(None, 1)
        return parts[0] + (" " + parts[1].upper() if len(parts) > 1 and parts[1] else " TD")
    return line


def _looks_like_mermaid_line(line: str) -> bool:
    lower = line.lower().strip()
    if lower.startswith("%%"):
        return True
    if lower == "end":
        return True
    if any(lower.startswith(s) for s in _MERMAID_STARTERS):
        return True
    if lower.startswith(("subgraph ", "direction ")):
        return True
    if _EDGE_RE.match(line) or _EDGE_LABEL_RE.match(line):
        return True
    if re.search(_ARROW_PATTERN, line):
        return True
    if re.match(r"^[A-Za-z_][\w]*\s*[\[\(\{<]", line):
        return True
    return False


def _normalize_edge_token(token: str) -> str:
    token = token.strip()
    if token.startswith("|") or "|" in token:
        return token
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", token)
    token = re.sub(r"\s+", "_", token)
    return _safe_id_token(token)


def _fix_spaced_edge_targets(line: str) -> str:
    """Merge accidental spaces inside node ids on edges."""
    label_match = _EDGE_LABEL_RE.match(line)
    if label_match:
        src = _normalize_edge_token(label_match.group(1))
        arrow_match = re.search(_ARROW_PATTERN, line)
        arrow = arrow_match.group(0) if arrow_match else "-->"
        label = _escape_label(label_match.group(2).strip())
        dst = _normalize_edge_token(label_match.group(3))
        return f'{src} {arrow}|"{label}"| {dst}'

    match = _EDGE_RE.match(line)
    if not match:
        return line
    arrow_match = re.search(_ARROW_PATTERN, line)
    arrow = arrow_match.group(0) if arrow_match else "-->"
    src = _normalize_edge_token(match.group(1))
    dst = _normalize_edge_token(match.group(2))
    return f"{src} {arrow} {dst}"


def _fix_relationship_node_labels(line: str) -> str:
    """VCC('powers') --> Power_Control  =>  VCC -->|'powers'| Power_Control"""
    match = re.match(
        rf'([A-Za-z_][\w]*)\("([^"]+)"\)\s*({_ARROW_PATTERN})\s*([A-Za-z_][\w]*)',
        line,
    )
    if not match:
        return line
    return (
        f'{match.group(1)} {match.group(3)}|"{_escape_label(match.group(2))}"| {match.group(4)}'
    )


def _fix_node_ids(line: str) -> str:
    return _fix_spaced_edge_targets(line)


def _safe_id_token(token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"[A-Za-z_][\w]*", token):
        return token
    safe = re.sub(r"[^\w]", "_", token).strip("_") or "Node"
    if safe[0].isdigit():
        safe = f"N_{safe}"
    return safe


def _quote_labels(line: str) -> str:
    def repl_square(match: re.Match[str]) -> str:
        node_id, label = match.group(1), match.group(2).strip()
        if label.startswith('"') and label.endswith('"'):
            return match.group(0)
        label = _escape_label(label)
        return f'{node_id}["{label}"]'

    line = re.sub(r'([A-Za-z_][\w]*)\[([^\]"]+)\]', repl_square, line)

    def repl_round(match: re.Match[str]) -> str:
        node_id, label = match.group(1), match.group(2).strip()
        if label.startswith('"') and label.endswith('"'):
            return match.group(0)
        label = _escape_label(label)
        return f'{node_id}("{label}")'

    line = re.sub(r'([A-Za-z_][\w]*)\(([^)"]+)\)', repl_round, line)

    def repl_subgraph(match: re.Match[str]) -> str:
        sid, label = match.group(1), match.group(2).strip()
        if label.startswith('"') and label.endswith('"'):
            return match.group(0)
        label = _escape_label(label)
        return f'subgraph {sid}["{label}"]'

    line = re.sub(
        r'(subgraph\s+[A-Za-z_][\w]*)\[([^\]"]+)\]',
        repl_subgraph,
        line,
        flags=re.IGNORECASE,
    )

    line = re.sub(
        r'\|([^|"][^|]*)\|',
        lambda m: f'|"{_escape_label(m.group(1).strip())}"|',
        line,
    )
    return line


def _escape_label(label: str) -> str:
    return label.replace('"', "'").replace("\n", " ")


def _dedupe_node_defs(code: str) -> str:
    """Drop duplicate node shape declarations with the same id."""
    seen_nodes: set[str] = set()
    output: list[str] = []
    node_decl = re.compile(
        r"^\s*([A-Za-z_][\w]*)\s*(\[\[|\{\{|\[\(|\[|\(\(|\(\[|\{)"
    )
    for line in code.splitlines():
        match = node_decl.match(line)
        if match:
            node_id = match.group(1)
            if node_id in seen_nodes and not re.search(_ARROW_PATTERN, line):
                continue
            seen_nodes.add(node_id)
        output.append(line)
    return "\n".join(output)
