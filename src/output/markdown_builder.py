"""Structured Markdown builder from knowledge graph."""

from __future__ import annotations

from src.models import DocumentBundle, ImplementationPlan, KnowledgeGraph


def build_markdown(
    plan: ImplementationPlan,
    kg: KnowledgeGraph,
    document: DocumentBundle | None = None,
) -> str:
    lines: list[str] = [
        f"# {plan.target_function or kg.title or 'Hardware Specification'}",
        "",
        "## Design Overview",
        "",
        "This document was automatically extracted and structured for AI agent consumption.",
        f"**Modules identified:** {len(plan.modules)}",
        f"**Graph nodes:** {len(kg.nodes)} | **Edges:** {len(kg.edges)}",
    ]

    if document:
        lines.extend([
            f"**Pages scanned:** {len(document.pages)}",
            f"**Tables extracted:** {len(document.tables)}",
            f"**Figures/diagrams:** {len(document.figures)}",
            "",
        ])

    if document and document.pages:
        lines.extend(["## Page Index", ""])
        lines.append("| Page | Characters | Tables | Figures | Diagram Page |")
        lines.append("|------|------------|--------|---------|--------------|")
        for p in document.pages:
            diag = "Yes" if p.is_diagram_page else "No"
            lines.append(
                f"| {p.page_num} | {p.char_count} | {p.table_count} | {p.figure_count} | {diag} |"
            )
        lines.append("")

    if plan.section_summaries:
        lines.extend(["## Section Summaries", ""])
        for s in plan.section_summaries:
            lines.append(f"### {s.title}")
            if s.purpose:
                lines.append(s.purpose)
            if s.key_concepts:
                lines.append(f"- **Key concepts:** {', '.join(s.key_concepts[:20])}")
            if s.figure_refs:
                lines.append(f"- **Figures:** {', '.join(s.figure_refs)}")
            lines.append("")

    if document and document.tables:
        lines.extend(["## Extracted Tables", ""])
        for t in document.tables:
            lines.append(f"### {t.caption} (`{t.id}`)")
            lines.append(f"*Page {t.page} — {t.row_count} rows × {t.col_count} cols*")
            lines.append("")
            if t.markdown:
                lines.append(t.markdown)
            lines.append("")

    lines.extend(["## Module Specifications", ""])
    for module in sorted(plan.modules, key=lambda m: m.order):
        lines.append(f"### Module: {module.name}")
        if module.description:
            lines.append(module.description)
        lines.append("")

        if module.inputs or module.outputs:
            lines.append("#### Interface")
            lines.append("| Direction | Signal |")
            lines.append("|-----------|--------|")
            for inp in module.inputs:
                lines.append(f"| Input | {inp} |")
            for out in module.outputs:
                lines.append(f"| Output | {out} |")
            lines.append("")

        if module.functionality:
            lines.append("#### Functionality")
            lines.append(module.functionality)
            lines.append("")

        if module.constraints:
            lines.append("#### Constraints")
            for c in module.constraints:
                lines.append(f"- {c}")
            lines.append("")

        if module.steps:
            lines.append("#### Implementation Steps")
            for step in module.steps:
                lines.append(f"1. {step}")
            lines.append("")

        if module.dependencies:
            lines.append(f"**Dependencies:** {', '.join(module.dependencies)}")
        if module.references:
            lines.append(f"**Spec references:** {', '.join(module.references)}")
        lines.append("")

    if document and document.pages:
        lines.extend(["## Page-by-Page Text", ""])
        for p in document.pages:
            if not p.text.strip():
                continue
            lines.append(f"### Page {p.page_num}")
            preview = p.text.strip()
            if len(preview) > 8000:
                preview = preview[:8000] + "\n\n...(truncated)..."
            lines.append(preview)
            lines.append("")

    lines.extend(["## Knowledge Graph Index", ""])
    for node in kg.nodes:
        port_str = ", ".join(f"{p.direction}:{p.name}" for p in node.ports[:8])
        lines.append(f"- **{node.id}** ({node.type}): {node.description or node.label}")
        if port_str:
            lines.append(f"  - Ports: {port_str}")
        if node.spec_ref:
            lines.append(f"  - Ref: {node.spec_ref}")

    return "\n".join(lines)
