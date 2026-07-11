"""Content auditor agent - validates module specification completeness."""

from __future__ import annotations

from src.llm.ollama_client import OllamaClient
from src.models import ModuleSpec


AUDITOR_SYSTEM = """You are a hardware specification quality auditor. Validate module descriptions
for completeness and readiness. Respond ONLY with valid JSON."""

AUDITOR_PROMPT = """Audit this hardware module specification for completeness.

Module JSON:
{module_json}

Evaluate across four dimensions:
1. Structural completeness (inputs, outputs with bit widths)
2. Correctness and clarity of functionality
3. Implementation steps present
4. Specification references present

Respond with JSON:
{{
  "valid": true or false,
  "issues": ["list of specific issues"],
  "suggestions": ["actionable improvements"]
}}"""


def audit_module(client: OllamaClient, module: ModuleSpec) -> ModuleSpec:
    # Rule-based pre-check
    issues: list[str] = []
    if not module.inputs:
        issues.append("Missing input port definitions")
    if not module.outputs:
        issues.append("Missing output port definitions")
    if not module.functionality:
        issues.append("Missing functionality description")

    if not issues:
        module.valid = True
        return module

    prompt = AUDITOR_PROMPT.format(module_json=module.model_dump_json())
    try:
        raw = client.chat_text(prompt, system=AUDITOR_SYSTEM, json_mode=True)
        data = client.parse_json_response(raw)
        module.valid = bool(data.get("valid", False))
        module.audit_issues = data.get("issues", issues)
    except Exception:
        module.valid = len(issues) == 0
        module.audit_issues = issues

    return module


def audit_with_retry(
    client: OllamaClient,
    document,
    modules: list[ModuleSpec],
    specify_fn,
    max_retries: int = 2,
) -> list[ModuleSpec]:
    from src.agents.specifier import specify_module

    result: list[ModuleSpec] = []
    for module in modules:
        current = module
        for _ in range(max_retries + 1):
            current = audit_module(client, current)
            if current.valid:
                break
            current = specify_module(client, document, current)
        result.append(current)
    return result
