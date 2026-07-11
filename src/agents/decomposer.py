"""Decomposition agent - hierarchical module identification."""

from __future__ import annotations

import json

from src.llm.ollama_client import OllamaClient
from src.models import DocumentBundle, ModuleSpec, SectionSummary


DECOMPOSER_SYSTEM = """You are a hardware architect. Decompose specifications into hierarchical
modules with dependencies. Respond ONLY with valid JSON."""

DECOMPOSER_PROMPT = """Given these section summaries and specification excerpts, identify all hardware
modules/submodules needed to implement the design.

Section summaries:
{summaries}

Full spec excerpt (first 8000 chars):
{excerpt}

Produce JSON:
{{
  "target_function": "name of the top-level design",
  "modules": [
    {{
      "name": "ModuleName",
      "description": "functional role",
      "order": 1,
      "dependencies": ["OtherModule"],
      "references": ["Section X.Y"]
    }}
  ]
}}

Order modules by implementation dependency (leaf modules first). Include at least the major blocks
mentioned in the specification."""


def decompose_modules(
    client: OllamaClient,
    document: DocumentBundle,
    summaries: list[SectionSummary],
) -> tuple[str, list[ModuleSpec]]:
    summaries_text = json.dumps([s.model_dump() for s in summaries[:30]], indent=2)
    excerpt = document.raw_text[:12000]
    if document.tables:
        table_hints = "\n".join(
            f"Table {t.id} p{t.page}: {t.rows[0] if t.rows else t.caption}"
            for t in document.tables[:25]
        )
        excerpt = excerpt + "\n\nTABLE HEADERS:\n" + table_hints

    prompt = DECOMPOSER_PROMPT.format(summaries=summaries_text, excerpt=excerpt)
    try:
        raw = client.chat_text(prompt, system=DECOMPOSER_SYSTEM, json_mode=True)
        data = client.parse_json_response(raw)
        target = data.get("target_function", document.title)
        modules = []
        for m in data.get("modules", []):
            modules.append(
                ModuleSpec(
                    name=m.get("name", "Unknown"),
                    description=m.get("description", ""),
                    order=m.get("order", 0),
                    dependencies=m.get("dependencies", []),
                    references=m.get("references", []),
                )
            )
        if not modules:
            modules = _fallback_modules(document)
        return target, modules
    except Exception:
        return document.title, _fallback_modules(document)


def _fallback_modules(document: DocumentBundle) -> list[ModuleSpec]:
    """Heuristic module extraction when LLM fails."""
    modules: list[ModuleSpec] = []
    keywords = [
        "ALU", "Register", "Decoder", "Control", "Memory", "Cache",
        "Bus", "Interface", "FIFO", "UART", "SPI", "Clock", "Reset",
        "Processor", "Core", "Pipeline", "Multiplier", "Adder",
    ]
    found: set[str] = set()
    text = document.raw_text
    for kw in keywords:
        if re_search_word(text, kw) and kw not in found:
            found.add(kw)
            modules.append(
                ModuleSpec(
                    name=kw + "Unit" if kw in ("Control", "Clock", "Reset") else kw,
                    description=f"Inferred {kw} block from specification text",
                    references=["auto-detected"],
                )
            )
    if not modules:
        modules.append(
            ModuleSpec(
                name="TopModule",
                description="Top-level design module",
                references=["Document"],
            )
        )
    return modules


def re_search_word(text: str, word: str) -> bool:
    import re
    return bool(re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE))
