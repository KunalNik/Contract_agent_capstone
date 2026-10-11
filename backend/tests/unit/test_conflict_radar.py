"""Unit tests for the Cross-Contract Conflict Radar (judge, service, repository, migrations, seed, API)."""
import pytest

from conflict_fakes import RuleLLM, msa_sow_store
from conftest import StubLLMManager

from backend.agents.conflict_judge_agent import ConflictJudge
from backend.application.services.conflict_detection_service import (
    ConflictDetectionFailedError,
    ConflictDetectionService,
    ContractNotFoundError,
    GoverningContractNotLinkedError,
)
from backend.domain.contracts.conflicts import ClausePair, ClauseRef

TENANT = "default-tenant"
CONFLICTING = ("Payment Terms", "Cap On Liability", "Governing Law")


def _pair(clause_type="Payment Terms"):
    return ClausePair(ClauseRef("S1", clause_type, "Pay within 90 days."),
                      ClauseRef("M1", clause_type, "Pay within 30 days."))


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    import backend.infrastructure.audit_logger as al
    monkeypatch.setattr(al.AuditLogger, "log_event", lambda *a, **k: "audit")


# ---------------------------------------------------------------- judge
def test_judge_reports_a_confirmed_conflict():
    finding = ConflictJudge(RuleLLM(conflicting=["Payment Terms"])).assess(_pair())
    assert finding is not None
    assert (finding.conflict_type, finding.severity) == ("inconsistent_timeline", "HIGH")
    assert finding.suggested_resolution == "Align Payment Terms"
    assert finding.verification_reason == "checked Payment Terms"


def test_judge_drops_a_conflict_rejected_on_verification():
    llm = RuleLLM(conflicting=["Payment Terms"], rejected=["Payment Terms"])
    assert ConflictJudge(llm).assess(_pair()) is None
    assert len(llm.prompts) == 2


def test_judge_skips_verification_when_no_conflict():
    llm = RuleLLM()
    assert ConflictJudge(llm).assess(_pair()) is None
    assert len(llm.prompts) == 1


def test_judge_normalises_unknown_type_and_severity():
    llm = RuleLLM(conflicting=["Payment Terms"], severity="catastrophic", conflict_type="made_up")
    finding = ConflictJudge(llm).assess(_pair())
    assert (finding.conflict_type, finding.severity) == ("other", "MEDIUM")


def test_judge_clips_very_long_clauses():
    llm = RuleLLM()
    long_pair = ClausePair(ClauseRef("S1", "Payment Terms", "x" * 10_000), ClauseRef("M1", "Payment Terms", "y"))
    ConflictJudge(llm).assess(long_pair)
    assert len(llm.prompts[0]) < 5_000


# ---------------------------------------------------------------- service
def test_service_reports_only_confirmed_conflicts(fake_graph):
    store = msa_sow_store(fake_graph)
    llm = RuleLLM(conflicting=CONFLICTING, rejected=["Governing Law"])
    result = ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(llm), "m")
    assert result.status == "completed"
    assert result.pairs_checked == 4  # the 'unknown' clause is never paired
    assert sorted(f.pair.clause.clause_id for f in result.findings) == ["S1", "S2"]
    assert [c["clause"]["clause_id"] for c in store.conflicts[(TENANT, "SOW1")]] == ["S1", "S2"]


def test_service_requires_an_existing_contract(fake_graph):
    msa_sow_store(fake_graph)
    with pytest.raises(ContractNotFoundError):
        ConflictDetectionService().detect_conflicts("NOPE", TENANT, ConflictJudge(RuleLLM()), "m")


def test_service_requires_a_governing_contract(fake_graph):
    msa_sow_store(fake_graph, linked=False)
    with pytest.raises(GoverningContractNotLinkedError):
        ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM()), "m")


def test_service_never_reports_a_total_llm_failure_as_no_conflicts(fake_graph):
    store = msa_sow_store(fake_graph)
    llm = RuleLLM(failing=CONFLICTING + ("Termination For Convenience",))
    with pytest.raises(ConflictDetectionFailedError):
        ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(llm), "m")
    assert store.status == {}  # nothing stored


def test_service_marks_partial_failures(fake_graph):
    store = msa_sow_store(fake_graph)
    llm = RuleLLM(conflicting=["Payment Terms"], failing=["Governing Law"])
    result = ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(llm), "m")
    assert (result.status, result.pairs_failed) == ("partial", 1)
    assert [f.pair.clause.clause_id for f in result.findings] == ["S1"]
    assert store.status[(TENANT, "SOW1")]["status"] == "partial"


def test_service_with_no_candidate_pairs_completes_with_zero_conflicts(fake_graph):
    store = msa_sow_store(fake_graph)
    store.clauses[(TENANT, "SOW1")] = [("S9", "unknown", "nothing comparable")]
    result = ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM()), "m")
    assert (result.status, result.pairs_checked, result.findings) == ("completed", 0, [])


def test_service_rejects_self_link(fake_graph):
    msa_sow_store(fake_graph)
    with pytest.raises(ValueError):
        ConflictDetectionService().link_governing_contract("SOW1", "SOW1", TENANT)


def test_relinking_clears_results_from_the_previous_governing_contract(fake_graph):
    store = msa_sow_store(fake_graph)
    service = ConflictDetectionService()
    service.detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM(conflicting=CONFLICTING)), "m")
    assert store.conflicts[(TENANT, "SOW1")]
    service.link_governing_contract("SOW1", "MSA2", TENANT)
    assert store.conflicts[(TENANT, "SOW1")] == []
    assert service.get_conflicts("SOW1", TENANT)["governing_contract"]["contract_id"] == "MSA2"


def test_service_flags_a_check_capped_by_the_pair_limit(fake_graph, monkeypatch):
    import backend.application.services.conflict_detection_service as svc
    store = msa_sow_store(fake_graph)  # 4 comparable pairs

    monkeypatch.setattr(svc, "MAX_PAIRS", 2)
    capped = ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM()), "m")
    assert (capped.pairs_checked, capped.pairs_truncated) == (2, True)
    assert store.status[(TENANT, "SOW1")]["pairs_truncated"] is True

    monkeypatch.setattr(svc, "MAX_PAIRS", 4)
    exact = ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM()), "m")
    assert (exact.pairs_checked, exact.pairs_truncated) == (4, False)


# ---------------------------------------------------------------- repository
def test_saving_results_is_one_atomic_statement(fake_graph):
    store = msa_sow_store(fake_graph)
    ConflictDetectionService().detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM(conflicting=CONFLICTING)), "m")
    writes = [q for q, _ in fake_graph.calls if "CONFLICTS_WITH" in q and ("DELETE" in q or "CREATE" in q)]
    assert len(writes) == 1 and store.saves == 1
    assert "DELETE old" in writes[0] and "CREATE (a)-[:CONFLICTS_WITH" in writes[0]


def test_candidate_query_returns_one_row_per_clause_pair(fake_graph):
    from backend.infrastructure.conflict_repository import ConflictRepository
    ConflictRepository().find_candidate_pairs("SOW1", TENANT, min_similarity=0.8, max_pairs=5)
    query, _ = fake_graph.calls[-1]
    # Grouping by (a, b) collapses clauses with several CUAD classifications into one pair
    assert "WITH a, b, similarity," in query and "collect(a_type)[0]" in query


def test_every_repository_query_is_tenant_scoped(fake_graph):
    msa_sow_store(fake_graph)
    service = ConflictDetectionService()
    service.link_governing_contract("SOW1", "MSA1", TENANT)
    service.detect_conflicts("SOW1", TENANT, ConflictJudge(RuleLLM(conflicting=CONFLICTING)), "m")
    service.get_conflicts("SOW1", TENANT)
    assert fake_graph.calls
    for query, params in fake_graph.calls:
        assert params.get("tenant_id") == TENANT, query
        assert "$tenant_id" in query, query


def test_candidate_query_is_bounded_and_skips_generic_types(fake_graph):
    from backend.infrastructure.conflict_repository import ConflictRepository
    ConflictRepository().find_candidate_pairs("SOW1", TENANT, min_similarity=0.8, max_pairs=7)
    query, params = fake_graph.calls[-1]
    assert "vector.similarity.cosine" in query and "gds." not in query
    assert params["max_pairs"] == 7 and params["min_similarity"] == 0.8
    assert "unknown" in params["generic_types"]


# ---------------------------------------------------------------- migrations
def test_migrations_apply_once_and_are_recorded(fake_graph):
    from backend.migrations import conflict_radar_schema
    from backend.migrations.runner import apply_pending

    assert apply_pending(fake_graph()) == [conflict_radar_schema.ID]
    executed = [q for q, _ in fake_graph.calls]
    assert all(s in executed for s in conflict_radar_schema.STATEMENTS)
    assert any("MERGE (m:SchemaMigration" in q for q in executed)

    fake_graph.calls.clear()
    fake_graph.handlers.append((r"MATCH \(m:SchemaMigration\) RETURN", lambda p: [{"id": conflict_radar_schema.ID}]))
    assert apply_pending(fake_graph()) == []
    assert not any(s in [q for q, _ in fake_graph.calls] for s in conflict_radar_schema.STATEMENTS)


def test_migration_statements_are_idempotent():
    from backend.migrations import conflict_radar_schema
    assert all("IF NOT EXISTS" in s for s in conflict_radar_schema.STATEMENTS)


def test_startup_migration_failure_does_not_raise(monkeypatch):
    import backend.migrations.runner as runner

    def boom(graph=None):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(runner, "apply_pending", boom)
    runner.apply_pending_on_startup()  # must not raise


# ---------------------------------------------------------------- seed data
def test_seed_data_is_idempotent_and_plants_conflicts(fake_graph):
    from backend.migrations.seed_data import SEED_CONTRACTS, remove_seed_data, seed_data

    seed_data(fake_graph(), "t1")
    writes = [q for q, _ in fake_graph.calls]
    assert writes and all("CREATE " not in q.replace("ON CREATE", "") for q in writes)
    assert all(p["tenant_id"] == "t1" for _, p in fake_graph.calls)

    msa = next(c for c in SEED_CONTRACTS if c["file_id"] == "SEED_MSA_001")
    sow = next(c for c in SEED_CONTRACTS if c["governed_by"] == "SEED_MSA_001")
    shared_types = {t for t, _ in msa["clauses"]} & {t for t, _ in sow["clauses"]}
    assert {"Payment Terms", "Cap On Liability", "Governing Law"} <= shared_types

    # Re-seeding resets every seed contract before re-linking, so manual tests can be repeated
    resets = [p["file_id"] for q, p in fake_graph.calls if "DELETE link" in q]
    assert sorted(resets) == sorted(c["file_id"] for c in SEED_CONTRACTS)
    reset_query = next(q for q, _ in fake_graph.calls if "DELETE link" in q)
    assert "CONFLICTS_WITH" in reset_query and "REMOVE c.conflict_check_status" in reset_query
    order = [("reset" if "DELETE link" in q else "link") for q, _ in fake_graph.calls
             if "DELETE link" in q or "MERGE (child)-[link:GOVERNED_BY]" in q]
    assert order.index("link") > order.index("reset")

    fake_graph.calls.clear()
    remove_seed_data(fake_graph(), "t1")
    (query, params), = fake_graph.calls
    assert "n.seed = true" in query and params == {"tenant_id": "t1"}


# ---------------------------------------------------------------- API
@pytest.fixture
def api(client):
    from backend.api import conflict_radar_api

    def use_llm(llm):
        client.app.dependency_overrides[conflict_radar_api.get_llm_manager] = lambda: StubLLMManager(llm)

    use_llm(RuleLLM(conflicting=CONFLICTING))
    yield client, use_llm
    client.app.dependency_overrides.clear()


def test_api_link_check_and_read_conflicts(api, fake_graph):
    client, _ = api
    msa_sow_store(fake_graph, linked=False)

    linked = client.put("/api/intelligence/contracts/SOW1/governing-contract", json={"governing_contract_id": "MSA1"})
    assert linked.status_code == 200, linked.text
    assert linked.json()["governing_contract"] == {"contract_id": "MSA1", "name": "msa.pdf"}

    before = client.get("/api/intelligence/contracts/SOW1/conflicts").json()
    assert (before["status"], before["conflicts"]) == ("not_run", [])

    checked = client.post("/api/intelligence/contracts/SOW1/conflicts")
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["status"] == "completed" and body["pairs_checked"] == 4
    assert sorted(c["clause"]["clause_id"] for c in body["conflicts"]) == ["S1", "S2", "S3"]
    conflict = body["conflicts"][0]
    assert {"conflict_type", "severity", "explanation", "suggested_resolution", "verification_reason",
            "clause", "governing_clause"} <= conflict.keys()

    assert client.get("/api/intelligence/contracts/SOW1/conflicts").json()["conflicts"] == body["conflicts"]


@pytest.mark.parametrize("contract, governing, expected", [
    ("SOW1", "SOW1", 400),
    ("SOW1", "MISSING", 404),
    ("MISSING", "MSA1", 404),
])
def test_api_link_errors(api, fake_graph, contract, governing, expected):
    client, _ = api
    msa_sow_store(fake_graph, linked=False)
    r = client.put(f"/api/intelligence/contracts/{contract}/governing-contract",
                   json={"governing_contract_id": governing})
    assert r.status_code == expected


def test_api_link_requires_upload_permission(api, fake_graph):
    client, _ = api
    msa_sow_store(fake_graph, linked=False)
    r = client.put("/api/intelligence/contracts/SOW1/governing-contract",
                   json={"governing_contract_id": "MSA1"}, headers={"X-User-Role": "VIEWER"})
    assert r.status_code == 403


def test_api_check_without_governing_contract_is_409(api, fake_graph):
    client, _ = api
    msa_sow_store(fake_graph, linked=False)
    assert client.post("/api/intelligence/contracts/SOW1/conflicts").status_code == 409


def test_api_total_llm_failure_is_502(api, fake_graph):
    client, use_llm = api
    msa_sow_store(fake_graph)
    use_llm(RuleLLM(failing=CONFLICTING + ("Termination For Convenience",)))
    assert client.post("/api/intelligence/contracts/SOW1/conflicts").status_code == 502


def test_api_without_any_llm_is_503(api, fake_graph):
    client, _ = api
    msa_sow_store(fake_graph)

    class NoModels(StubLLMManager):
        def get_chat_model(self, name=None):
            raise ValueError("No LLM models available")

    from backend.api import conflict_radar_api
    client.app.dependency_overrides[conflict_radar_api.get_llm_manager] = lambda: NoModels(None)
    assert client.post("/api/intelligence/contracts/SOW1/conflicts").status_code == 503


def test_api_internal_errors_return_a_reference_not_details(api, fake_graph):
    client, _ = api
    from backend.api import conflict_radar_api

    class Broken(ConflictDetectionService):
        def get_conflicts(self, contract_id, tenant_id):
            raise RuntimeError("bolt://admin:s3cret@db failed")

    client.app.dependency_overrides[conflict_radar_api.get_conflict_service] = lambda: Broken()
    r = client.get("/api/intelligence/contracts/SOW1/conflicts", headers={"X-Correlation-ID": "trace-500"})
    assert r.status_code == 500
    assert "s3cret" not in r.text and "trace-500" in r.json()["detail"]


def test_api_tags_llm_calls_with_the_request_correlation_id(api, fake_graph):
    client, use_llm = api
    msa_sow_store(fake_graph)
    llm = RuleLLM()
    use_llm(llm)
    client.post("/api/intelligence/contracts/SOW1/conflicts", headers={"X-Correlation-ID": "trace-123"})
    assert "correlation_id:trace-123" in llm.tags


def test_api_audit_is_written_off_the_event_loop(api, fake_graph, monkeypatch):
    import asyncio
    import backend.infrastructure.audit_logger as al
    client, _ = api
    msa_sow_store(fake_graph, linked=False)
    events = []

    def spy(self, **kwargs):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = False
        events.append((kwargs["action"], kwargs["tenant_id"], on_loop))

    monkeypatch.setattr(al.AuditLogger, "log_event", spy)
    client.put("/api/intelligence/contracts/SOW1/governing-contract", json={"governing_contract_id": "MSA1"})
    client.post("/api/intelligence/contracts/SOW1/conflicts")
    assert events == [("link_governing_contract", TENANT, False), ("detect_conflicts", TENANT, False)]


def test_api_other_tenants_cannot_read_or_check(api, fake_graph):
    client, _ = api
    msa_sow_store(fake_graph)
    other = {"X-Tenant-ID": "someone-else"}
    assert client.get("/api/intelligence/contracts/SOW1/conflicts", headers=other).status_code == 404
    assert client.post("/api/intelligence/contracts/SOW1/conflicts", headers=other).status_code == 404
