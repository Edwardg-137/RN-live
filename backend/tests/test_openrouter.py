import httpx
import pytest

from rn_live.config import Settings
from rn_live.openrouter import OpenRouterClient, OpenRouterConfigurationError, OpenRouterError


def transport(response):
    def handler(request):
        assert request.url.path == "/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        return response
    return httpx.MockTransport(handler)


def test_free_model_sends_chat_completion_and_returns_text():
    response = httpx.Response(200, json={"choices":[{"message":{"content":"Respuesta de prueba"}}]})
    client = OpenRouterClient(Settings(openrouter_api_key="test-key"), transport=transport(response))
    result = client.complete([{"role":"user","content":"Hola"}])
    assert result.text == "Respuesta de prueba"
    assert result.model == "openrouter/free"


def test_settings_accept_openrouter_environment_names(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/free")
    assert Settings().openrouter_api_key == "environment-key"


def test_missing_key_does_not_make_request():
    client = OpenRouterClient(Settings(openrouter_api_key=""), transport=transport(httpx.Response(500)))
    with pytest.raises(OpenRouterConfigurationError, match="OPENROUTER_API_KEY"):
        client.complete([{"role":"user","content":"Hola"}])


def test_free_mode_rejects_paid_model():
    settings = Settings(openrouter_api_key="test-key", openrouter_model="openai/gpt-5")
    client = OpenRouterClient(settings, transport=transport(httpx.Response(200, json={})))
    with pytest.raises(OpenRouterConfigurationError, match="gratuito"):
        client.complete([{"role":"user","content":"Hola"}])


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_errors_are_safe_and_actionable(status):
    response = httpx.Response(status, json={"error":{"message":"provider detail"}})
    client = OpenRouterClient(Settings(openrouter_api_key="test-key"), transport=transport(response))
    with pytest.raises(OpenRouterError, match=str(status)):
        client.complete([{"role":"user","content":"Hola"}])
