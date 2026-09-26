"""Regression tests: patterns, supervisor, MCP, feedback, search, audit, cache, chunking."""
import asyncio
import json

import pytest

MSA = ("1. Payment Terms. Client shall pay within ninety (90) days, net 90. "
       "2. Limitation of Liability. Supplier accepts unlimited liability for all claims. ") * 3


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import backend.infrastructure.audit_logger as al
    monkeypatch.setattr(al.AuditLogger, "log_event", lambda *a, **k: "audit")


def _contract_row(p):
    return [{"file_id": p.get("contract_id", "C1"), "contract_type": "MSA", "summary": "s", "contract_scope": "",
             "full_text": MSA, "effective_date": None, "end_date": None, "total_amount": None, "parties": []}]


# ---------------------------------------------------------------- patterns
def test_patterns_endpoints_work(client):
    body = {"query": "termination", "contract_text": MSA, "clauses": [{"clause_type": "Liability", "content": "unlimited liability"}]}
    react = client.post("/api/patterns/react", json={**body, "max_iterations": 2})
    assert react.status_code == 200 and react.json()["success"] is True
    cot = client.post("/api/patterns/chain-of-thought", json=body)
    assert cot.status_code == 200 and cot.json()["success"] is True
    combined = client.post("/api/patterns/analyze", json={**body, "patterns": ["react", "cot"]})
    assert combined.status_code == 200 and combined.json()["success"] is True


# ---------------------------------------------------------------- supervisor
def test_supervisor_runs_existing_contract_once_and_reports_status(client, fake_graph, monkeypatch):
    fake_graph.handlers.append((r"MATCH \(c:Contract \{file_id: \$contract_id, tenant_id", _contract_row))
    import backend.api.supervisor_api as sa
    monkeypatch.setattr(sa, "_supervisor", None)

    from backend.agents.contract_intelligence_agents import IntelligenceOrchestrator
    calls = []
    original = IntelligenceOrchestrator.analyze_contract
    monkeypatch.setattr(IntelligenceOrchestrator, "analyze_contract",
                        lambda self, *a, **k: calls.append(1) or original(self, *a, **k))

    r = client.post("/api/supervisor/workflow/execute", headers={"X-Tenant-ID": "acme"},
                    json={"workflow_id": "wf1", "input_data": {"contract_id": "C1", "tenant_id": "evil"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["results"]["clause_extraction"]["clauses"]
    assert body["results"]["risk_assessment"]["risk_level"] in ("HIGH", "CRITICAL")
    assert len(calls) == 1  # analysis shared between clause and risk steps
    lookups = [p for q, p in fake_graph.calls if "MATCH (c:Contract {file_id: $contract_id, tenant_id" in q]
    assert all(p["tenant_id"] == "acme" for p in lookups)

    assert client.get("/api/supervisor/workflow/wf1/status", headers={"X-Tenant-ID": "acme"}).status_code == 200
    assert client.get("/api/supervisor/workflow/wf1/status", headers={"X-Tenant-ID": "other"}).status_code == 404


def test_supervisor_without_inputs_fails_honestly(client, monkeypatch):
    import backend.api.supervisor_api as sa
    monkeypatch.setattr(sa, "_supervisor", None)
    r = client.post("/api/supervisor/workflow/execute", json={"input_data": {}})
    assert r.status_code == 200 and r.json()["status"] == "failed"


# ---------------------------------------------------------------- MCP
def test_mcp_fetch_contract_metadata(fake_graph, monkeypatch):
    fake_graph.handlers.append((r"MATCH \(c:Contract \{file_id: \$contract_id, tenant_id", _contract_row))
    import backend.mcp_server as m
    fn = getattr(m.fetch_contract_metadata, "fn", m.fetch_contract_metadata)
    out = json.loads(asyncio.run(fn(contract_id="C1", tenant_id="t1")))
    assert out["success"] is True and out["metadata"]["file_id"] == "C1"
    monkeypatch.setenv("MCP_TENANT_ID", "t1")
    denied = json.loads(asyncio.run(fn(contract_id="C1", tenant_id="t2")))
    assert denied["status"] == "failed"


# ---------------------------------------------------------------- feedback
def test_feedback_analytics_with_no_decisions(client, fake_graph):
    fake_graph.handlers.append((r"count\(d\) as total_decisions", lambda p: [{
        "total_decisions": 0, "approved_count": 0, "rejected_count": 0, "modified_count": 0,
        "avg_confidence": None, "clause_types": []}]))
    r = client.get("/api/feedback/analytics/dashboard")
    assert r.status_code == 200 and r.json()["average_confidence"] == 0.0


def test_feedback_for_unknown_contract_is_404_and_invalid_decision_rejected(client):
    base = {"contract_id": "nope", "clause_id": "c", "clause_type": "Liability", "original_analysis": {},
            "legal_feedback": "ok"}
    assert client.post("/api/feedback/legal-decision", json={**base, "legal_decision": "approved"}).status_code == 404
    assert client.post("/api/feedback/legal-decision", json={**base, "legal_decision": "maybe"}).status_code == 422


def test_learned_approval_pattern_needs_keywords():
    from backend.agents.feedback_learning_system import AdaptiveAnalyzer, FeedbackPattern
    pattern = FeedbackPattern("p", "approval", {"common_keywords": []}, "likely_approved", 0.5)
    assert AdaptiveAnalyzer()._apply_approval_pattern({"content": "anything"}, {}, pattern) is None


# ---------------------------------------------------------------- search
def test_clause_search_endpoint_returns_results_for_tenant(client, fake_graph):
    fake_graph.handlers.append((r"HAS_SECTION\|CONTAINS_CLAUSE\*1\.\.2\]->\(cl:Clause\)", lambda p: [{"result": {
        "total_count": 1, "clauses": [{"contract_id": "C1", "clause_type": "Governing Law", "content": "x", "confidence": 0.9}]}}]))
    r = client.post("/api/contracts/search/clauses", headers={"X-Tenant-ID": "acme"}, json={"clause_types": ["Governing Law"]})
    assert r.status_code == 200 and r.json() is not None
    assert r.json()["contracts_found"] == 1
    params = fake_graph.calls[-1][1]
    assert params["tenant_id"] == "acme"


def test_search_errors_are_not_reported_as_empty_results(client, fake_graph):
    def boom(p):
        raise RuntimeError("database unavailable")
    fake_graph.handlers.append((r"MATCH \(c:Contract\)", boom))
    r = client.post("/api/contracts/search/enhanced", json={"search_level": "document"})
    assert r.status_code == 500 and "database unavailable" in r.json()["detail"]


# ---------------------------------------------------------------- audit / cache / chunking
def test_audit_ids_are_unique(monkeypatch, fake_graph):
    import importlib
    import backend.infrastructure.audit_logger as al
    importlib.reload(al)  # undo the autouse stub for this test
    logger = al.AuditLogger()
    for _ in range(50):
        logger.log_event(al.AuditEventType.SEARCH_QUERY, "r", "a")
    ids = [p["audit_id"] for q, p in fake_graph.calls if "MERGE (a:AuditLog" in q]
    assert len(ids) == 50 and len(set(ids)) == 50


def test_in_memory_cache_expires_and_is_bounded(monkeypatch):
    from backend.shared.cache.redis_cache import InMemoryCache
    c = InMemoryCache(max_entries=3)
    c.setex("a", 1, "1")
    for k in "bcd":
        c.setex(k, 100, k)
    assert c.get("a") is None and len(c._cache) == 3
    now = __import__("time").time()
    monkeypatch.setattr("time.time", lambda: now + 1000)
    assert c.get("b") is None


def test_cache_keys_ignore_instance_identity(monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "true")
    from backend.shared.cache.redis_cache import cache_result
    calls = []

    class Svc:
        @cache_result("unit_test", ttl=60, method=True)
        def get(self, x):
            calls.append(x)
            return {"x": x}

    assert Svc().get(1) == Svc().get(1) == {"x": 1}
    assert calls == [1]


@pytest.mark.parametrize("strategy", ["sentence", "paragraph", "section", "clause", "hybrid", "policy", "auto"])
def test_every_chunking_strategy_can_be_built(strategy):
    from backend.infrastructure.chunking.factory import ChunkingFactory
    text = "1. Payment. Client shall pay within 30 days.\n\n2. Term. The agreement lasts one year.\n" * 10
    st = ChunkingFactory.create_strategy(strategy)
    out = st.chunk_text(text, {}) if hasattr(st, "chunk_text") else st.chunk_document(text, {})
    assert out
