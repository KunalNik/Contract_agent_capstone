import os
from typing import Any, Dict, Optional

from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

from backend.contract_chat_agent import get_agent


# Model registry: public name -> (env var that enables it, factory for the raw chat model)
def _openai(model: str):
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model, temperature=0)


def _gemini(model: str):
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(model=model, temperature=0)


def _anthropic(model: str):
    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=model, temperature=0)


def _mistral(model: str):
    from langchain_mistralai import ChatMistralAI
    return ChatMistralAI(model=model)


MODEL_REGISTRY = {
    "gpt-4o": (("OPENAI_API_KEY",), lambda: _openai("gpt-4o")),
    "gemini-2.5-pro": (("GOOGLE_API_KEY", "GEMINI_API_KEY"), lambda: _gemini("gemini-2.5-pro")),
    "gemini-2.5-flash": (("GOOGLE_API_KEY", "GEMINI_API_KEY"), lambda: _gemini("gemini-2.5-flash")),
    "claude-sonnet": (("ANTHROPIC_API_KEY",), lambda: _anthropic(os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"))),
    "mistral-large": (("MISTRAL_API_KEY",), lambda: _mistral("mistral-large-latest")),
}

DEFAULT_MODEL = "gemini-2.5-flash"


class LLMManager:
    """Holds one raw chat model and one tool-calling chat agent per configured provider.

    - ``get_chat_model(name)`` returns the plain chat model (``.invoke(str)`` works);
      use it for guards, analysis and extraction.
    - ``get_model_by_name(name)`` returns the LangGraph chat agent used by /api/run.
    """

    def __init__(self):
        # Instance-level (the old class-level dict was shared by every instance)
        self.chat_models: Dict[str, Any] = {}
        self.agents: Dict[str, Any] = {}
        self.init_agents()

    def init_agents(self):
        if os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"):
            # langchain-google-genai reads GOOGLE_API_KEY; honour the documented fallback
            os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

        for name, (env_vars, factory) in MODEL_REGISTRY.items():
            if not any(os.getenv(v) for v in env_vars):
                continue
            try:
                model = factory()
                self.chat_models[name] = model
                self.agents[name] = get_agent(model)
            except Exception as e:  # a bad provider config must not take the app down
                logger.error(f"Failed to initialise model '{name}': {e}")
        logger.info(f"Loaded {len(self.agents)} llms.")

    def available_models(self):
        return list(self.agents.keys())

    def get_model_by_name(self, name: str):
        """Return the tool-calling chat agent (LangGraph) for /api/run."""
        try:
            return self.agents[name]
        except KeyError:
            raise ValueError(
                f"The model {name} wasn't initiated. Available: {self.available_models() or 'none (check API keys)'}"
            )

    def get_chat_model(self, name: Optional[str] = None):
        """Return the raw chat model; falls back to the default, then any configured model."""
        name = name or DEFAULT_MODEL
        if name in self.chat_models:
            return self.chat_models[name]
        if DEFAULT_MODEL in self.chat_models:
            logger.warning(f"Model '{name}' not configured, using '{DEFAULT_MODEL}'")
            return self.chat_models[DEFAULT_MODEL]
        if self.chat_models:
            fallback = next(iter(self.chat_models))
            logger.warning(f"Model '{name}' not configured, using '{fallback}'")
            return self.chat_models[fallback]
        raise ValueError("No LLM models available - set GOOGLE_API_KEY (or another provider key)")


_shared_manager: Optional[LLMManager] = None


def get_shared_llm_manager() -> LLMManager:
    """Process-wide LLMManager for code outside request scope (guards, agents)."""
    global _shared_manager
    if _shared_manager is None:
        _shared_manager = LLMManager()
    return _shared_manager


def set_shared_llm_manager(manager: LLMManager) -> None:
    global _shared_manager
    _shared_manager = manager
