"""Specifier agent - detailed module interface extraction."""

from __future__ import annotations

import json

from src.llm.ollama_client import OllamaClient
from src.models import DocumentBundle, ModuleSpec


SPECIFIER_SYSTEM = """You are a hardware design engineer. Extract precise module specifications
including ports, behavior, and constraints. Respond ONLY with valid JSON."""

SPECIFIER_PROMPT = """Extract detailed implementation specification for module "{name}".

Module description: {description}
Spec references: {references}

Relevant specification text:
{context}

Produce JSON:
{{
  "name": "{name}",
  "description": "detailed description",
  "inputs": ["signal_name (width-bit description)"],
  "outputs": ["signal_name (width-bit description)"],
  "functionality": "behavioral description",
  "constraints": ["constraint 1"],
  "steps": ["implementation step 1"],
  "references": ["Section X.Y"]
}}"""


def specify_module(
    client: OllamaClient,
    document: DocumentBundle,
    module: ModuleSpec,
) -> ModuleSpec:
    context = _find_relevant_context(document, module)
    prompt = SPECIFIER_PROMPT.format(
        name=module.name,
        description=module.description,
        references=", ".join(module.references),
        context=context[:5000],
    )
    try:
        raw = client.chat_text(prompt, system=SPECIFIER_SYSTEM, json_mode=True)
        data = client.parse_json_response(raw)
        return ModuleSpec(
            name=data.get("name", module.name),
            description=data.get("description", module.description),
            inputs=data.get("inputs", []),
            outputs=data.get("outputs", []),
            functionality=data.get("functionality", ""),
            constraints=data.get("constraints", []),
            steps=data.get("steps", []),
            references=data.get("references", module.references),
            order=module.order,
            dependencies=module.dependencies,
        )
    except Exception:
        return module


def specify_all_modules(
    client: OllamaClient,
    document: DocumentBundle,
    modules: list[ModuleSpec],
) -> list[ModuleSpec]:
    return [specify_module(client, document, m) for m in modules]


def _find_relevant_context(document: DocumentBundle, module: ModuleSpec) -> str:
    name_lower = module.name.lower()
    parts: list[str] = []
    for section in document.sections:
        if name_lower in section.content.lower() or name_lower in section.title.lower():
            parts.append(f"## {section.title}\n{section.content}")
    if parts:
        return "\n\n".join(parts)
    return document.raw_text[:6000]
