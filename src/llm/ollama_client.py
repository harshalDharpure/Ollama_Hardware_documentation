"""Ollama client for text and vision LLM calls."""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

import requests



def _model_names(models: list[str]) -> set[str]:
    names: set[str] = set()
    for model in models:
        names.add(model)
        if ":" in model:
            names.add(model.split(":", 1)[0])
    return names


def _model_available(requested: str, available: list[str]) -> bool:
    return bool(requested) and requested in available


def resolve_ollama_model(requested: str, available: list[str], fallback: str | None = None) -> str:
    """Pick an installed Ollama model, preferring exact match then configured fallback."""
    if _model_available(requested, available):
        return requested
    if fallback and _model_available(fallback, available):
        return fallback
    prefix = requested.split(":", 1)[0] if requested and ":" in requested else requested
    for model in available:
        if model.startswith(f"{prefix}:") or model == prefix:
            return model
    return fallback or requested


def resolve_ollama_models(
    base_url: str,
    text_model: str,
    vision_model: str,
    text_fallback: str | None = None,
    vision_fallback: str | None = None,
) -> tuple[str, str, list[str]]:
    """Return text/vision models that exist on the Ollama server."""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
        resp.raise_for_status()
        available = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
    except Exception:
        return text_model, vision_model, []

    resolved_text = resolve_ollama_model(text_model, available, text_fallback)
    resolved_vision = resolve_ollama_model(vision_model, available, vision_fallback)
    return resolved_text, resolved_vision, available


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        text_model: str = "qwen2.5:7b",
        vision_model: str = "llava:7b",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.text_model = text_model
        self.vision_model = vision_model
        self.timeout = timeout

    def _post_json(self, url: str, payload: dict[str, Any], retries: int = 3) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                if resp.status_code in {500, 502, 503, 504} and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("Ollama request failed")

    def health_check(self) -> dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return {
                "ok": True,
                "models": models,
                "text_available": _model_available(self.text_model, models),
                "vision_available": _model_available(self.vision_model, models),
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

        resp = self._post_json(f"{self.base_url}/api/chat", payload)
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

        resp = self._post_json(
            f"{self.base_url}/api/chat",
            {
                "model": model or self.vision_model,
                "messages": messages,
                "stream": False,
            },
        )
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
