"""The model registry only loads providers whose API key is configured."""
from backend.llm_manager import LLMManager


def test_claude_haiku_is_available_when_an_anthropic_key_is_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    manager = LLMManager()
    assert "claude-haiku" in manager.available_models()
    assert manager.get_chat_model("claude-haiku").model == "claude-haiku-4-5"


def test_claude_models_are_absent_without_an_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    models = LLMManager().available_models()
    assert "claude-haiku" not in models and "claude-sonnet" not in models
