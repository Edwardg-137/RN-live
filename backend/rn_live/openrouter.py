from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


class OpenRouterError(RuntimeError):
    """Error returned by, or while contacting, OpenRouter."""


class OpenRouterConfigurationError(OpenRouterError):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    usage: dict[str, Any] | None = None


class OpenRouterClient:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.openrouter_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.openrouter_timeout_seconds),
            transport=transport,
        )

    def close(self):
        self._client.close()

    def _validate(self):
        if not self.settings.openrouter_api_key.strip():
            raise OpenRouterConfigurationError("Configura OPENROUTER_API_KEY para usar el proveedor")
        model = self.settings.openrouter_model.strip()
        if not model:
            raise OpenRouterConfigurationError("Configura OPENROUTER_MODEL")
        if self.settings.openrouter_free_only and model != "openrouter/free" and not model.endswith(":free"):
            raise OpenRouterConfigurationError("El modo gratuito solo permite openrouter/free o modelos :free")
        return model

    def complete(self, messages: list[dict[str, str]], *, max_tokens: int = 800, temperature: float = 0.1) -> Completion:
        model = self._validate()
        if not messages or any(message.get("role") not in {"system", "user", "assistant"} or not message.get("content", "").strip() for message in messages):
            raise OpenRouterConfigurationError("Los mensajes deben tener role y content válidos")
        headers = {"Authorization": f"Bearer {self.settings.openrouter_api_key}"}
        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_app_title:
            headers["X-OpenRouter-Title"] = self.settings.openrouter_app_title
        try:
            response = self._client.post(
                "/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            )
        except httpx.HTTPError as exc:
            raise OpenRouterError("No se pudo conectar con OpenRouter") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("error", {}).get("message", ""))
            except ValueError:
                pass
            suffix = f": {detail[:240]}" if detail else ""
            raise OpenRouterError(f"OpenRouter respondió HTTP {response.status_code}{suffix}")
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty content")
            return Completion(text=text, model=payload.get("model", model), usage=payload.get("usage"))
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError("OpenRouter devolvió una respuesta sin contenido utilizable") from exc
