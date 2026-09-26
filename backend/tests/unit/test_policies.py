"""Regression tests for policy management."""
import pytest

from pdf_fixture import make_pdf

POLICY_TEXT = """SECTION 1: LIABILITY POLICY
The company shall never accept unlimited liability in any contract.
All contracts must include a liability cap equal to fees paid.
SECTION 2: TERMINATION REQUIREMENTS
Contracts must provide a notice period of at least thirty days before termination.
Immediate termination without notice is prohibited.
"""


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    import backend.infrastructure.audit_logger as al
    monkeypatch.setattr(al.AuditLogger, "log_event", lambda *a, **k: "audit")


def test_policy_upload_processes_and_stores_rules(client, fake_graph):
    r = client.post("/api/policies/upload", headers={"X-Tenant-ID": "acme"},
                    files={"file": ("policy.txt", POLICY_TEXT.encode())}, data={"policy_name": "Legal Playbook"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["policy_id"].startswith("policy_acme_")
    doc_writes = [p for q, p in fake_graph.calls if "MERGE (p:PolicyDocument {id: $document_id})" in q]
    assert doc_writes[0]["tenant_id"] == "acme" and doc_writes[0]["name"] == "Legal Playbook"
    rule_writes = [p for q, p in fake_graph.calls if "CREATE (r:PolicyRule" in q]
    assert rule_writes and all(p["embedding"] and p["applies_to"] for p in rule_writes)


def test_policy_upload_accepts_pdf_and_rejects_unknown_formats(client):
    pdf = make_pdf(POLICY_TEXT.splitlines())
    ok = client.post("/api/policies/upload", files={"file": ("p.pdf", pdf)}, data={"policy_name": "P"})
    assert ok.status_code == 200, ok.text
    bad = client.post("/api/policies/upload", files={"file": ("p.docx", b"PK\x03\x04")}, data={"policy_name": "P"})
    assert bad.status_code == 415


def test_tenant_listing_and_not_found_status_codes(client, fake_graph):
    assert client.get("/api/policies/tenant", headers={"X-Tenant-ID": "acme"}).status_code == 200
    assert client.get("/api/policies/tenant/other", headers={"X-Tenant-ID": "acme"}).status_code == 403
    assert client.get("/api/policies/nope").status_code == 404
    assert client.delete("/api/policies/nope").status_code == 404


def test_policy_queries_exclude_soft_deleted(fake_graph):
    from backend.infrastructure.policy_repository import PolicyRepository
    repo = PolicyRepository()
    repo.get_policies_by_tenant("t")
    repo.get_applicable_policies("t", "liability")
    assert all("coalesce(p.active, true)" in q for q, _ in fake_graph.calls)


def test_semantic_search_uses_builtin_vector_function(fake_graph):
    from backend.infrastructure.policy_repository import PolicyRepository
    PolicyRepository().search_policies_semantic("liability cap", "t")
    query = fake_graph.calls[-1][0]
    assert "vector.similarity.cosine(r.embedding" in query and "gds." not in query


def test_compliance_check_matches_clause_types(client, fake_graph):
    fake_graph.handlers.append((r"HAS_RULE\]->\(r:PolicyRule\)", lambda p: [{
        "id": "r1", "rule_text": "Unlimited liability is prohibited", "rule_type": "prohibited",
        "applies_to": ["liability"], "severity": "CRITICAL", "section_reference": "1"}]))
    r = client.post("/api/policies/compliance/check", json={
        "contract_clauses": [{"clause_type": "Limitation of Liability", "content": "Supplier accepts unlimited liability"}]})
    assert r.status_code == 200, r.text
    assert r.json()["compliance_check"]["violations_found"] == 1
