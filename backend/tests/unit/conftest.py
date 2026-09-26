"""
Offline test harness.

Stubs the Neo4j driver and Gemini embeddings so the real app, services and
agents can be imported and exercised without credentials or network access.
Tests control database responses through the ``fake_graph`` fixture.
"""
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-dummy-key")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CACHE_ENABLED", "false")
os.environ["TRACING_ENABLED"] = "false"


class FakeGraph:
    """In-memory stand-in for langchain_neo4j.Neo4jGraph.

    ``handlers`` is a list of (regex, callable(params) -> rows). The first
    matching handler answers; unmatched queries return []. Every call is
    recorded in ``calls`` for assertions.
    """

    handlers: List[Tuple[str, Callable[[Dict[str, Any]], list]]] = []
    calls: List[Tuple[str, Dict[str, Any]]] = []

    def __init__(self, *args, **kwargs):
        pass

    def query(self, query: str, params: Optional[Dict[str, Any]] = None):
        params = params or {}
        FakeGraph.calls.append((query, params))
        for pattern, handler in FakeGraph.handlers:
            if re.search(pattern, query, re.S):
                return handler(params)
        return []

    def refresh_schema(self):
        pass

    schema = ""


class FakeEmbedding:
    dimensions = 1536

    def embed_query(self, text: str) -> List[float]:
        seed = (sum(map(ord, text)) % 97) / 97.0 + 0.01
        return [seed] * self.dimensions

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]

    def generate_embedding(self, text: str) -> List[float]:
        return self.embed_query(text)

    async def generate_embedding_async(self, text: str) -> List[float]:
        return self.embed_query(text)


# Patch before any backend module is imported
import langchain_neo4j  # noqa: E402
import langchain_neo4j.graphs.neo4j_graph as _neo4j_graph_module  # noqa: E402

langchain_neo4j.Neo4jGraph = FakeGraph
_neo4j_graph_module.Neo4jGraph = FakeGraph

import backend.shared.utils.gemini_embedding_service as _ges  # noqa: E402

_ges.GeminiEmbeddingService._instance = None
_fake_embedding = FakeEmbedding()
_ges.GeminiEmbeddingService.__new__ = lambda cls, *a, **k: _fake_embedding  # type: ignore
_ges.GeminiEmbeddingService.__init__ = lambda self, *a, **k: None  # type: ignore
if hasattr(_ges, "embedding"):
    _ges.embedding = _fake_embedding


@pytest.fixture(autouse=True)
def fake_graph():
    FakeGraph.handlers = []
    FakeGraph.calls = []
    yield FakeGraph
    FakeGraph.handlers = []
    FakeGraph.calls = []


@pytest.fixture
def fake_llm_factory():
    """Build a chat model that returns canned responses in order."""
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    class _Fake(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    def make(*contents: str):
        return _Fake(responses=[AIMessage(content=c) for c in contents])

    return make


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class StubLLMManager:
    """LLMManager stand-in backed by fake chat models."""

    def __init__(self, chat_model, agent=None):
        self.chat_model = chat_model
        self.agent = agent
        self.agents = {"gemini-2.5-flash": agent} if agent is not None else {}
        self.chat_models = {"gemini-2.5-flash": chat_model}

    def available_models(self):
        return list(self.agents)

    def get_chat_model(self, name=None):
        return self.chat_model

    def get_model_by_name(self, name):
        if name not in self.agents:
            raise ValueError(f"The model {name} wasn't initiated")
        return self.agents[name]


@pytest.fixture
def use_fake_llm(fake_llm_factory):
    """Install a shared fake LLM manager; returns a setter taking canned responses."""
    import backend.llm_manager as lm

    previous = lm._shared_manager

    def install(*responses, agent=None):
        mgr = StubLLMManager(fake_llm_factory(*responses) if responses else fake_llm_factory("{}"), agent)
        lm.set_shared_llm_manager(mgr)
        return mgr

    yield install
    lm._shared_manager = previous


@pytest.fixture(autouse=True)
def _no_audit_writes(monkeypatch):
    """Audit/agent logging would hit the fake graph anyway; keep calls cheap."""
    yield
