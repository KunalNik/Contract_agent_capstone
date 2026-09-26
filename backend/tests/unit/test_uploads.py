"""Regression tests for the document upload paths."""
import json
import os

import pytest

from pdf_fixture import SAMPLE_CONTRACT_LINES, make_pdf
from conftest import StubLLMManager

ANALYSIS = json.dumps({
    "is_contract": True, "confidence_score": 92, "contract_type": "MSA",
    "summary": "Master services agreement between Acme and Beta",
    "parties": [{"name": "Acme Corp", "role": "Client"}, "Beta LLC"],
    "effective_date": "January 15, 2024", "end_date": "2024-02-30",
    "total_amount": "$1,200,000", "governing_law": "Delaware", "key_terms": ["net 90"],
})


@pytest.fixture
def pdf_bytes():
    return make_pdf(SAMPLE_CONTRACT_LINES)


@pytest.fixture
def upload_env(client, fake_graph, fake_llm_factory, monkeypatch, tmp_path):
    import backend.infrastructure.audit_logger as al
    monkeypatch.setattr(al.AuditLogger, "log_event", lambda *a, **k: "audit")
    monkeypatch.setenv("UPLOAD_TMP_DIR", str(tmp_path))
    import backend.api.document_upload as du
    monkeypatch.setattr(du, "UPLOAD_DIR", str(tmp_path))

    stored = {}

    def create_contract(params):
        stored.update(params)
        return [{"contract_id": params["file_id"]}]

    fake_graph.handlers.append((r"CREATE \(c:Contract", create_contract))
    client.app.state.llm_manager = StubLLMManager(fake_llm_factory(*([ANALYSIS] * 5)))
    return {"client": client, "stored": stored, "tmp": tmp_path, "graph": fake_graph}


def test_upload_stores_contract_with_tenant_hash_and_valid_fields(upload_env, pdf_bytes):
    c = upload_env["client"]
    r = c.post("/api/documents/upload?model=gemini-2.5-flash", headers={"X-Tenant-ID": "acme"},
               files={"file": ("../../etc/msa.pdf", pdf_bytes, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["contract_id"].startswith("UPLOADED_")
    stored = upload_env["stored"]
    assert stored["tenant_id"] == "acme"
    assert stored["content_hash"] and stored["original_filename"] == "../../etc/msa.pdf"
    assert stored["effective_date"] == "2024-01-15"
    assert stored["end_date"] is None            # invalid date is dropped, not sent to date()
    assert stored["total_amount"] == 1200000.0
    # temp file written inside the upload dir and cleaned up
    assert os.listdir(upload_env["tmp"]) == []
    # chunks are linked to the stored contract and tagged with the tenant
    doc_writes = [p for q, p in upload_env["graph"].calls if "MERGE (d:Document {id: $document_id})" in q]
    assert doc_writes and doc_writes[0]["document_id"] == body["contract_id"] and doc_writes[0]["tenant_id"] == "acme"


def test_duplicate_upload_is_detected_per_tenant(upload_env, pdf_bytes):
    graph = upload_env["graph"]
    graph.handlers.insert(0, (r"MATCH \(c:Contract \{tenant_id: \$tenant_id, content_hash", lambda p: [{"file_id": "UPLOADED_OLD"}] if p["tenant_id"] == "acme" else []))
    c = upload_env["client"]
    r = c.post("/api/documents/upload", headers={"X-Tenant-ID": "acme"}, files={"file": ("a.pdf", pdf_bytes)})
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    assert r.json()["existing_contract_id"] == "UPLOADED_OLD"
    other = c.post("/api/documents/upload", headers={"X-Tenant-ID": "other"}, files={"file": ("a.pdf", pdf_bytes)})
    assert other.json()["status"] == "success"


def test_non_pdf_is_rejected_with_400(upload_env):
    r = upload_env["client"].post("/api/documents/upload", files={"file": ("a.txt", b"hello")})
    assert r.status_code == 400


def test_enhanced_upload_endpoint_works(upload_env, pdf_bytes):
    r = upload_env["client"].post("/api/documents/enhanced/upload", headers={"X-Tenant-ID": "acme"},
                                  files={"file": ("m.pdf", pdf_bytes)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success" and body["contract_id"]
    assert upload_env["stored"]["tenant_id"] == "acme"


def test_enhanced_upload_without_embeddings_path(upload_env, pdf_bytes):
    r = upload_env["client"].post("/api/documents/enhanced/upload?enable_embeddings=false",
                                  files={"file": ("m.pdf", pdf_bytes)})
    assert r.status_code == 200 and r.json()["status"] == "success"


def test_full_processing_upload_builds_enhanced_graph(upload_env, pdf_bytes):
    r = upload_env["client"].post("/api/documents/upload?enable_enhanced=true",
                                  files={"file": ("m.pdf", pdf_bytes)})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"
    assert "Sections:" in r.json()["details"]


def test_upload_stream_reports_progress(upload_env, pdf_bytes):
    r = upload_env["client"].post("/api/documents/upload-stream", files={"file": ("m.pdf", pdf_bytes)})
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types.count("progress") == 3 and "completion" in types and types[-1] == "end"


def test_section_regex_ignores_ordinary_short_lines():
    from backend.agents.section_extraction_agent import RegexSectionExtractor
    text = "1. Payment Terms\nthe parties agree\nClient pays monthly.\nTERMINATION\nEither party may end it."
    titles = [s.title for s in RegexSectionExtractor().extract_sections(text)]
    assert titles == ["1. Payment Terms", "TERMINATION"]
