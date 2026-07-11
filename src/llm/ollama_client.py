"""Ollama client for text and vision LLM calls."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import requests


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        text_model: str = "qwen2.5:7b",
        vision_model: str = "llava:13b",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.text_model = text_model
        self.vision_model = vision_model
        self.timeout = timeout

    def health_check(self) -> dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return {
                "ok": True,
                "models": models,
                "text_available": any(self.text_model.split(":")[0] in m for m in models),
                "vision_available": any(self.vision_model.split(":")[0] in m for m in models),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "models": []}

    def chat_text(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
        model: str | None = None,
    ) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model or self.text_model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return content.strip()

    def chat_vision(
        self,
        prompt: str,
        image_path: str | Path,
        system: str = "",
        model: str | None = None,
    ) -> str:
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": prompt,
                "images": [b64],
            }
        )

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": model or self.vision_model,
                "messages": messages,
                "stream": False,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()

    @staticmethod
    def parse_json_response(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                return json.loads(match.group())
            raise
