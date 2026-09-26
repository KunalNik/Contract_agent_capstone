"""
Offline reproduction harness for BUG_REPORT.md / AUDIT_REPORT.md findings.

Runs the real FastAPI app and agent code with Neo4j and Gemini stubbed out,
so every check works without credentials or network access.

Usage (from repo root):
    cd backend && uv sync && cd ..
    PYTHONPATH=. backend/.venv/bin/python scripts/repro_bugs.py

Each line prints: [ID] PASS/FAIL  <what was expected>  ->  <what happened>
"FAIL" means the bug reproduced. On the fixed code every check should PASS;
the full regression suite lives in backend/tests/unit (run: pytest -q).
"""
import asyncio
import json
import os
import sys
from typing import TypedDict

os.environ.setdefault("GOOGLE_API_KEY", "repro-dummy-key")

# --- Stub Neo4j before any backend import (the app connects at import time) ---
import langchain_neo4j  # noqa: E402
import langchain_neo4j.graphs.neo4j_graph as _ng  # noqa: E402


class FakeGraph:
    def __init__(self, *a, **k):
        pass

    def query(self, q, params=None):
        if "avg(c.risk_score)" in q:  # dashboard aggregate over zero analysed contracts
            return [{"total_analyzed": 0, "avg_risk_score": None, "high_risk_count": 0,
                     "total_violations": None, "total_clauses": None, "total_redlines": None}]
        if "content_hash: $content_hash" in q and q.lstrip().startswith("MATCH"):  # duplicate check finds a match
            return [{"file_id": "UPLOADED_X_nda"}]
        return []

    def refresh_schema(self):
        pass


langchain_neo4j.Neo4jGraph = FakeGraph
_ng.Neo4jGraph = FakeGraph

# Stub audit persistence so checks don't depend on the DB
import backend.infrastructure.audit_logger as _al  # noqa: E402

_al.AuditLogger.log_event = lambda self, *a, **k: "audit_stub"

RESULTS = []


def check(bug_id, expectation, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # an unexpected exception is itself a reproduction
        ok, detail = False, f"raised {type(e).__name__}: {e}"
    RESULTS.append((bug_id, ok))
    print(f"[{bug_id}] {'PASS' if ok else 'FAIL'}  {expectation}  ->  {str(detail)[:160]}")


# ---------------------------------------------------------------- governance
def prompt_guard():
    from backend.governance.prompt_guard import PromptGuard
    r = PromptGuard().validate("What are the termination clauses?")
    return r.is_safe, f"is_safe={r.is_safe}"


def intent_validator():
    from backend.governance.validators.intent import IntentValidator
    r = IntentValidator().validate("Summarize the termination clause of the Acme agreement")
    return True, f"is_safe={r.is_safe}"


def guard_llm_call():
    """Guards must use a raw chat model (invoke(str)), not the LangGraph chat agent."""
    import inspect
    from backend.governance import llm_judge
    src = inspect.getsource(llm_judge.ask_json)
    ok = "get_chat_model" in src and "get_model_by_name" not in src
    return ok, "guards resolve models via get_chat_model" if ok else "guards still use the chat agent"


def topic_validator():
    from backend.governance.validators.topic import TopicValidator
    q = "What are the payment terms?"
    r = TopicValidator().validate(q)
    return r.is_safe, f"'{q}' -> is_safe={r.is_safe} {r.violation_type or ''}"


def keyword_validator():
    from backend.governance.validators.keyword import KeywordValidator
    q = "list the administrative fees clause"
    r = KeywordValidator().validate(q)
    return r.is_safe, f"'{q}' -> is_safe={r.is_safe} {r.violation_type or ''}"


# ---------------------------------------------------------------- intelligence
def clause_detector_hardcoded():
    from backend.agents.intelligence_tools import ClauseDetectorTool
    t = ClauseDetectorTool()
    a = t._run("This NDA has no payment or liability terms at all.")
    b = t._run("Master Services Agreement. Payment net 90. Unlimited liability.")
    return a != b, f"two different contracts -> identical output: {a == b}"


def ip_substring():
    from backend.agents.intelligence_tools import PolicyCheckerTool
    clause = [{"clause_type": "Shipping", "content": "client owns all shipping labels"}]
    v = json.loads(PolicyCheckerTool()._run(json.dumps(clause)))
    return not v, f"'Shipping' clause flagged as IP violation: {bool(v)}"


def traditional_path_asyncio():
    from backend.agents.contract_intelligence_agents import IntelligenceOrchestrator

    text = ("1. Payment Terms. Client shall pay within ninety (90) days, net 90. "
            "2. Limitation of Liability. Supplier accepts unlimited liability for all claims. ") * 80

    async def inside_loop():
        orch = IntelligenceOrchestrator(llm=None)
        return orch.analyze_contract(text, use_planning=False)

    r = asyncio.run(inside_loop())
    return bool(r.get("clauses")), f"clauses={len(r.get('clauses', []))} risk={r.get('risk_assessment')}"


def enhanced_upload_sync_invoke():
    """The enhanced service must run the agent (which has an async node) asynchronously."""
    import inspect
    from backend.application.services.enhanced_document_processing_service import EnhancedDocumentProcessingService
    ok = inspect.iscoroutinefunction(EnhancedDocumentProcessingService.process_pdf_with_embeddings)
    return ok, f"process_pdf_with_embeddings is async: {ok}"


def chat_tool_tenant_from_llm():
    from backend.shared.utils.contract_search_tool import ContractInput
    fields = ContractInput.model_fields
    llm_controls = "tenant_id" in fields and "cypher_aggregation" in fields
    return not llm_controls, f"LLM-fillable args include tenant_id={('tenant_id' in fields)}, cypher_aggregation={('cypher_aggregation' in fields)}"


def mcp_fetch_metadata():
    import backend.mcp_server as m
    fn = getattr(m.fetch_contract_metadata, "fn", m.fetch_contract_metadata)
    out = json.loads(asyncio.run(fn(contract_id="X", tenant_id="t1")))
    return out.get("success") is not False or "coroutine" not in str(out), out


def basic_upload_embeddings():
    from backend.application.services.document_processing_service import DocumentProcessingService
    service = DocumentProcessingService(agent_manager=None)
    has = hasattr(service.embedding_pipeline, "run")
    return has, f"basic upload service has an embedding pipeline: {has}"


# ---------------------------------------------------------------- HTTP endpoints
def http_checks():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        def ep(bug_id, desc, method, path, expect, **kw):
            def run():
                r = getattr(c, method)(path, **kw)
                return r.status_code == expect, f"HTTP {r.status_code} {r.text[:110]}"
            check(bug_id, desc, run)

        def chat():
            r = c.post("/api/run/", json={"model": "gemini-2.5-flash",
                                           "prompt": "What are the termination clauses?", "history": "[]"})
            return '"type": "end"' in r.text, f"HTTP {r.status_code}, body bytes={len(r.text)}"
        check("F1", "chat stream completes with an 'end' event", chat)

        ep("F9", "dashboard returns 200 with zero analysed contracts", "get",
           "/api/intelligence/dashboard/summary", 200)
        ep("F7", "patterns/react returns 200", "post", "/api/patterns/react", 200,
           json={"query": "termination", "contract_text": "x"})
        ep("F7", "patterns/chain-of-thought returns 200", "post", "/api/patterns/chain-of-thought", 200,
           json={"query": "termination", "clauses": []})
        ep("F6", "policy upload (text) returns 200", "post", "/api/policies/upload", 200,
           files={"file": ("p.txt", b"SECTION 1: LIABILITY POLICY\nLiability shall be capped and must never be unlimited.\n" * 5)},
           data={"policy_name": "p"})
        ep("F6", "tenant policy listing returns 200", "get", "/api/policies/tenant", 200)
        ep("F6", "unknown policy id returns 404", "get", "/api/policies/nope", 404)
        ep("F5", "duplicate upload returns 200 'duplicate'", "post", "/api/documents/upload", 200,
           files={"file": ("nda.pdf", b"%PDF-1.4 x")})
        os.environ["ENVIRONMENT"] = "production"
        os.environ["JWT_SECRET"] = "repro-secret-with-enough-length-12345"
        ep("S3", "production rejects requests without a token (even with a role header)", "get",
           "/api/audit/errors/recent", 401, headers={"X-User-Role": "ADMIN"})
        os.environ["ENVIRONMENT"] = "development"
        ep("S5", "debug endpoint listing all contracts is not mounted", "get",
           "/api/documents/debug/contracts", 404)

        def supervisor_status():
            c.post("/api/supervisor/workflow/execute", json={"workflow_id": "wf-repro", "input_data": {}})
            r = c.get("/api/supervisor/workflow/wf-repro/status")
            return r.status_code == 200, r.text[:110]
        check("F8", "supervisor status can find a workflow it ran", supervisor_status)


if __name__ == "__main__":
    print("== Governance ==")
    check("F1", "PromptGuard evaluates a normal prompt", prompt_guard)
    check("F1", "IntentValidator handles a 5+ word prompt", intent_validator)
    check("F2", "guards can call the LLM with a string prompt", guard_llm_call)
    check("F3", "topic guard allows an on-topic question", topic_validator)
    check("F3", "keyword guard allows 'administrative'", keyword_validator)
    print("== Intelligence ==")
    check("F4", "clause detector output depends on the contract", clause_detector_hardcoded)
    check("F4", "'Shipping' clause is not treated as IP", ip_substring)
    check("F4", "non-planning path analyses a 12k-char contract", traditional_path_asyncio)
    print("== Upload / MCP / Search ==")
    check("F5", "graph with async node can be run the way enhanced upload runs it", enhanced_upload_sync_invoke)
    check("F5", "basic upload service can build multi-level embeddings", basic_upload_embeddings)
    check("F10", "MCP fetch_contract_metadata returns metadata or not-found", mcp_fetch_metadata)
    check("S1", "chat tool does not let the LLM choose tenant or raw Cypher", chat_tool_tenant_from_llm)
    print("== HTTP ==")
    http_checks()
    failed = [b for b, ok in RESULTS if not ok]
    print(f"\n{len(failed)}/{len(RESULTS)} checks reproduced a bug.")
