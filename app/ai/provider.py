"""LLM providers behind one small interface, so the model can be swapped in .env.

AI_PROVIDER=ollama   -> a local model through Ollama (default, free, offline)
AI_PROVIDER=disabled -> AI features are hidden
Tests use FakeProvider, so they never need a model running.
"""
from typing import Protocol

import httpx

from app.config import settings


class AIUnavailable(Exception):
    """The model can't be reached; the UI shows this message instead of an error page."""


class LLMProvider(Protocol):
    model_name: str

    def complete_json(self, system: str, user: str, schema: dict | None = None) -> str:
        """Return the model's raw text answer (expected to be JSON)."""


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def complete_json(self, system: str, user: str, schema: dict | None = None) -> str:
        body = {
            "model": self.model_name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": schema or "json",
            "options": {"temperature": 0.2},
        }
        try:
            response = self._client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.ConnectError as exc:
            raise AIUnavailable(f"Ollama is not running at {self.base_url}. Start it with 'ollama serve'.") from exc
        except httpx.TimeoutException as exc:
            raise AIUnavailable("The model took too long to answer. Try a shorter input or a smaller model.") from exc
        if response.status_code == 404:
            raise AIUnavailable(f"Model '{self.model_name}' is not installed. Run: ollama pull {self.model_name}")
        if response.status_code >= 400:
            raise AIUnavailable(f"Ollama error {response.status_code}: {response.text[:200]}")
        return response.json().get("message", {}).get("content", "")


class FakeProvider:
    """Returns canned answers in order. Used by tests."""

    def __init__(self, answers: list[str], model_name: str = "fake-model"):
        self.answers = list(answers)
        self.model_name = model_name
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, schema: dict | None = None) -> str:
        self.calls.append((system, user))
        if not self.answers:
            raise AIUnavailable("No more fake answers.")
        return self.answers.pop(0)


_override: LLMProvider | None = None


def set_provider(provider: LLMProvider | None) -> None:
    global _override
    _override = provider


def ai_enabled() -> bool:
    return _override is not None or settings.AI_PROVIDER.lower() != "disabled"


def get_provider() -> LLMProvider:
    if _override is not None:
        return _override
    if settings.AI_PROVIDER.lower() == "ollama":
        return OllamaProvider(settings.OLLAMA_URL, settings.OLLAMA_MODEL, settings.AI_TIMEOUT_SECONDS)
    raise AIUnavailable("AI features are turned off (AI_PROVIDER=disabled).")
