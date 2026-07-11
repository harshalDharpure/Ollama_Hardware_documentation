"""VLM-based Mermaid generation from diagrams."""

from __future__ import annotations

import re
from pathlib import Path

from src.llm.ollama_client import OllamaClient


MERMAID_UNLABELED_PROMPT = """You are an expert of electrical and hardware block diagrams.
Generate mermaid code for this diagram. Do not give any additional information in the output.
The objective is to understand all components and how they are connected.
Output ONLY valid mermaid syntax starting with 'graph TD' or 'flowchart LR'."""

MERMAID_LABELED_PROMPT = """You are an expert of electrical and hardware block diagrams.
Generate mermaid code for this diagram. Do not give any additional information in the output.
The objective is to understand all components and their connections.
To help understanding, connection nodes are labeled as 'J1', 'J2', etc. in red.
Component labels appear as 'C1', 'C2', etc. Nodes with the same J-label are electrically connected.
Output ONLY valid mermaid syntax starting with 'graph TD' or 'flowchart LR'."""


def generate_mermaid_from_diagram(
    client: OllamaClient,
    image_path: str | Path,
    labeled: bool = True,
) -> str:
    prompt = MERMAID_LABELED_PROMPT if labeled else MERMAID_UNLABELED_PROMPT
    try:
        raw = client.chat_vision(prompt, image_path)
        return extract_mermaid(raw)
    except Exception as exc:
        return f"graph TD\n    Error[\"Diagram parse failed: {exc}\"]"


def extract_mermaid(text: str) -> str:
    text = text.strip()
    if "```" in text:
        match = re.search(r"```(?:mermaid)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    for starter in ("graph ", "flowchart "):
        idx = text.find(starter)
        if idx >= 0:
            text = text[idx:]
            break
    if not text.startswith(("graph", "flowchart")):
        text = "graph TD\n" + text
    return text
