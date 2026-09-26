"""Regression tests for the contract intelligence pipeline."""
import asyncio
import json

import pytest

MSA = """MASTER SERVICES AGREEMENT
1. Payment Terms. Client shall pay all invoices within ninety (90) days, i.e. net 90 from receipt.
2. Limitation of Liability. The Supplier accepts unlimited liability for all claims, including consequential damages.
3. Termination. Either party may terminate this Agreement immediately without notice.
4. Governing Law. This Agreement is governed by the laws of the State of Delaware.
5. Shipping. Supplier shall ship goods using its preferred carrier and client owns all shipping labels.
"""

NDA = """MUTUAL NON-DISCLOSURE AGREEMENT
1. Confidentiality. Each party shall keep the other party's Confidential Information confidential for three years.
2. Governing Law. This Agreement is governed by the laws of England and Wales.
"""


@pytest.fixture(autouse=True)
def _quiet_audit(monkeypatch):
    import backend.infrastructure.audit_logger as al
    monkeypatch.setattr(al.AuditLogger, "log_event", lambda *a, **k: "audit")


def _clauses(text, llm=None):
    from backend.agents.intelligence_tools import ClauseDetectorTool
    return json.loads(ClauseDetectorTool(llm=llm)._run(text))


def test_clause_detector_reads_the_actual_contract():
    msa_types = {c["clause_type"] for c in _clauses(MSA)}
    nda_types = {c["clause_type"] for c in _clauses(NDA)}
    assert {"Payment Terms", "Liability", "Termination", "Governing Law"} <= msa_types
    assert "Confidentiality" in nda_types and "Payment Terms" not in nda_types
    assert all("Liability limited to $50,000" not in c["content"] for c in _clauses(MSA))


def test_clause_detector_uses_llm_when_available(fake_llm_factory):
    llm = fake_llm_factory(json.dumps({"clauses": [
        {"clause_type": "Payment Terms", "content": "Pay within 90 days", "risk_level": "high",
         "confidence_score": 1.7, "location": "1"}]}))
    clauses = _clauses("Pay within 90 days of invoice. " * 5, llm=llm)
    assert clauses == [{"clause_type": "Payment Terms", "content": "Pay within 90 days", "risk_level": "HIGH",
                        "confidence_score": 1.0, "location": "1", "extraction_method": "llm"}]


def test_clause_detector_falls_back_when_llm_fails(fake_llm_factory):
    clauses = _clauses(MSA, llm=fake_llm_factory("this is not json"))
    assert clauses and all(c["extraction_method"] == "heuristic" for c in clauses)


def test_shipping_clause_is_not_treated_as_ip():
    from backend.agents.intelligence_tools import PolicyCheckerTool
    clause = [{"clause_type": "Shipping", "content": "client owns all shipping labels"}]
    assert json.loads(PolicyCheckerTool()._run(json.dumps(clause))) == []


def test_no_clauses_gives_unknown_risk_not_a_fake_baseline():
    from backend.agents.intelligence_tools import RiskCalculatorTool
    risk = json.loads(RiskCalculatorTool()._run("[]", "[]"))
    assert risk["risk_level"] == "UNKNOWN" and risk["overall_risk_score"] == 0.0


@pytest.mark.parametrize("use_planning", [True, False])
def test_both_paths_work_inside_an_event_loop_and_agree(use_planning):
    """Non-planning path used to crash on asyncio.run for contracts > 10k chars."""
    from backend.agents.agent_workflow_tracker import workflow_tracker
    from backend.agents.contract_intelligence_agents import IntelligenceOrchestrator

    workflow_tracker.workflow_start_time = None  # fresh server state
    long_msa = MSA + ("Additional recitals and definitions apply. " * 300)

    async def inside_loop():
        return IntelligenceOrchestrator(llm=None).analyze_contract(long_msa, use_planning=use_planning)

    result = asyncio.run(inside_loop())
    assert result["processing_complete"] is True
    assert result.get("planned_execution", False) is use_planning
    assert result["clauses"]
    severities = {v["severity"] for v in result["violations"]}
    assert "CRITICAL" in severities  # unlimited liability / net 90
    assert result["redlines"]


def test_cot_agent_runs_and_uses_clause_type():
    from backend.agents.patterns.chain_of_thought_agent import ChainOfThoughtAgent
    result = asyncio.run(ChainOfThoughtAgent().execute({
        "clauses": [{"clause_type": "Liability", "content": "unlimited liability"}],
        "task_type": "risk_assessment"}))
    assert result["success"] is True
    assert result["thought_chain"][0]["output_data"]["identified_clauses"] == ["Liability"]


def test_precedent_matcher_no_longer_crashes():
    from backend.agents.optimized_cuad_tools import OptimizedPrecedentMatcherTool
    out = json.loads(OptimizedPrecedentMatcherTool()._run(json.dumps([{"clause_type": "Payment Terms", "content": "net 30"}])))
    assert out and out[0]["data_source"] == "illustrative_baseline"


def test_precedent_query_uses_real_relationships(fake_graph):
    from backend.agents.enhanced_cuad_tools import EnhancedPrecedentMatcherTool
    EnhancedPrecedentMatcherTool()._find_real_precedents({"clause_type": "liability", "content": "x"}, "t1")
    query, params = fake_graph.calls[-1]
    assert "CONTAINS_CLAUSE" in query and params["tenant_id"] == "t1"


# ---------------------------------------------------------------- API
def test_failed_analysis_is_reported_not_stored_as_completed(client, fake_graph, monkeypatch):
    fake_graph.handlers.append((r"MATCH \(c:Contract \{file_id: \$contract_id, tenant_id", lambda p: [{
        "file_id": "C1", "contract_type": "MSA", "summary": "s", "contract_scope": "", "full_text": MSA,
        "effective_date": None, "end_date": None, "total_amount": None, "parties": []}]))
    from backend.agents.contract_intelligence_agents import IntelligenceOrchestrator

    def boom(self, *a, **k):
        return {"processing_complete": False, "error": "LLM quota exceeded"}
    monkeypatch.setattr(IntelligenceOrchestrator, "analyze_contract", boom)

    r = client.post("/api/intelligence/contracts/C1/analyze")
    assert r.status_code == 502 and "LLM quota exceeded" in r.json()["detail"]
    writes = [q for q, _ in fake_graph.calls if "intelligence_status = $intelligence_status" in q]
    assert writes == []
    assert any("last_analysis_status = 'failed'" in q for q, _ in fake_graph.calls)


def test_analysis_endpoint_end_to_end(client, fake_graph):
    fake_graph.handlers.append((r"MATCH \(c:Contract \{file_id: \$contract_id, tenant_id", lambda p: [{
        "file_id": "C1", "contract_type": "MSA", "summary": "s", "contract_scope": "", "full_text": MSA,
        "effective_date": None, "end_date": None, "total_amount": None, "parties": []}]))
    r = client.post("/api/intelligence/contracts/C1/analyze", headers={"X-Tenant-ID": "acme"})
    assert r.status_code == 200, r.text
    body = r.json()["results"]
    assert {c["clause_type"] for c in body["clauses"]} >= {"Payment Terms", "Liability"}
    assert body["risk_assessment"]["risk_level"] in ("HIGH", "CRITICAL")
    lookup = [p for q, p in fake_graph.calls if "MATCH (c:Contract {file_id: $contract_id, tenant_id" in q]
    assert lookup[0]["tenant_id"] == "acme"


def test_dashboard_with_no_analysed_contracts(client, fake_graph):
    fake_graph.handlers.append((r"avg\(c.risk_score\)", lambda p: [{
        "total_analyzed": 0, "avg_risk_score": None, "high_risk_count": 0,
        "total_violations": None, "total_clauses": None, "total_redlines": None}]))
    r = client.get("/api/intelligence/dashboard/summary")
    assert r.status_code == 200
    assert r.json()["average_risk_score"] == 0.0
