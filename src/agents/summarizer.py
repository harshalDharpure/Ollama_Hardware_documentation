"""Summarizer agent - section-level structured summaries."""

from __future__ import annotations

from src.llm.ollama_client import OllamaClient
from src.models import DocumentBundle, SectionSummary


SUMMARIZER_SYSTEM = """You are a hardware specification analyst. Extract structured information
from specification sections. Respond ONLY with valid JSON."""

SUMMARIZER_PROMPT = """Analyze this hardware specification section and produce a JSON object with:
- section_id: "{section_id}"
- title: section title
- purpose: one paragraph describing the section purpose
- key_concepts: list of important technical terms and concepts
- figure_refs: list of referenced figures/tables (e.g. "Figure 2.1")
- dependencies: list of other sections or modules this section depends on

Section title: {title}

Section content:
{content}

Respond with JSON only."""


def summarize_sections(client: OllamaClient, document: DocumentBundle) -> list[SectionSummary]:
    summaries: list[SectionSummary] = []
    for section in document.sections:
        if len(section.content.strip()) < 20:
            summaries.append(
                SectionSummary(
                    section_id=section.id,
                    title=section.title,
                    purpose=section.content[:200],
                    figure_refs=section.figure_refs,
                )
            )
            continue

        content = section.content[:6000]
        prompt = SUMMARIZER_PROMPT.format(
            section_id=section.id,
            title=section.title,
            content=content,
        )
        try:
            raw = client.chat_text(prompt, system=SUMMARIZER_SYSTEM, json_mode=True)
            data = client.parse_json_response(raw)
            summaries.append(
                SectionSummary(
                    section_id=data.get("section_id", section.id),
                    title=data.get("title", section.title),
                    purpose=data.get("purpose", ""),
                    key_concepts=data.get("key_concepts", []),
                    figure_refs=data.get("figure_refs", section.figure_refs),
                    dependencies=data.get("dependencies", []),
                )
            )
        except Exception:
            summaries.append(
                SectionSummary(
                    section_id=section.id,
                    title=section.title,
                    purpose=section.content[:500],
                    figure_refs=section.figure_refs,
                )
            )
    return summaries
