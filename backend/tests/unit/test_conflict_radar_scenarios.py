"""BDD scenarios for the Cross-Contract Conflict Radar, exercised through the HTTP API.

Feature: Cross-Contract Conflict Radar
  As a contract manager
  I want a statement of work checked against the master agreement that governs it
  So that contradictions are caught before they cause disputes
"""
import pytest

from conflict_fakes import RuleLLM, msa_sow_store
from conftest import StubLLMManager

BASE = "/api/intelligence/contracts"
CONFLICTING = ("Payment Terms", "Cap On Liability", "Governing Law")


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    import backend.infrastructure.audit_logger as al
    monkeypatch.setattr(al.AuditLogger, "log_event", lambda *a, **k: "audit")


@pytest.fixture
def world(client, fake_graph):
    """Scenario context: the API client, the contract store and the LLM in use."""
    from backend.api import conflict_radar_api

    class World:
        def __init__(self):
            self.client, self.response, self.store = client, None, None

        def given_an_msa_and_a_sow(self, linked=False, tenant="default-tenant"):
            self.store = msa_sow_store(fake_graph, tenant=tenant, linked=linked)

        def given_the_llm(self, llm):
            client.app.dependency_overrides[conflict_radar_api.get_llm_manager] = lambda: StubLLMManager(llm)

        def when(self, method, path, **kwargs):
            self.response = getattr(client, method)(f"{BASE}{path}", **kwargs)
            return self.response

        def conflict_clause_ids(self):
            return sorted(c["clause"]["clause_id"] for c in self.response.json()["conflicts"])

    w = World()
    w.given_the_llm(RuleLLM(conflicting=CONFLICTING))
    yield w
    client.app.dependency_overrides.clear()


def test_scenario_sow_contradicting_its_msa_shows_confirmed_conflicts_only(world):
    # Given an MSA and a SOW that disagree on payment, liability and governing law
    world.given_an_msa_and_a_sow()
    # And the reviewer model rejects the governing-law finding on its second look
    world.given_the_llm(RuleLLM(conflicting=CONFLICTING, rejected=["Governing Law"]))
    # When I link the SOW to the MSA
    assert world.when("put", "/SOW1/governing-contract", json={"governing_contract_id": "MSA1"}).status_code == 200
    # And I run a conflict check
    assert world.when("post", "/SOW1/conflicts").status_code == 200
    # Then only the confirmed conflicts are reported, each with both clauses side by side
    assert world.conflict_clause_ids() == ["S1", "S2"]
    first = world.response.json()["conflicts"][0]
    assert first["clause"]["content"] and first["governing_clause"]["content"]
    # And the consistent termination clause is not reported
    assert "S4" not in world.conflict_clause_ids()


def test_scenario_checking_an_unlinked_contract_asks_to_link_first(world):
    # Given a SOW with no governing contract
    world.given_an_msa_and_a_sow(linked=False)
    # When I run a conflict check
    world.when("post", "/SOW1/conflicts")
    # Then I am told to link a governing contract first
    assert world.response.status_code == 409
    assert "link" in world.response.json()["detail"].lower()


def test_scenario_results_survive_a_page_reload(world):
    # Given a SOW that has been checked against its MSA
    world.given_an_msa_and_a_sow(linked=True)
    world.when("post", "/SOW1/conflicts")
    checked = world.response.json()
    # When I reopen the contract later
    world.when("get", "/SOW1/conflicts")
    # Then I see the stored results without running the check again
    assert world.response.json()["conflicts"] == checked["conflicts"]
    assert world.response.json()["governing_contract"]["contract_id"] == "MSA1"


def test_scenario_relinking_discards_stale_results(world):
    # Given a SOW checked against one MSA
    world.given_an_msa_and_a_sow(linked=True)
    world.when("post", "/SOW1/conflicts")
    assert world.conflict_clause_ids()
    # When I link it to a different MSA
    world.when("put", "/SOW1/governing-contract", json={"governing_contract_id": "MSA2"})
    # Then the old conflicts are gone and the new governing contract is shown
    world.when("get", "/SOW1/conflicts")
    assert world.response.json()["conflicts"] == []
    assert world.response.json()["governing_contract"]["contract_id"] == "MSA2"


def test_scenario_llm_outage_is_reported_and_previous_results_are_kept(world):
    # Given a SOW with stored conflict results
    world.given_an_msa_and_a_sow(linked=True)
    world.when("post", "/SOW1/conflicts")
    previous = world.conflict_clause_ids()
    # And the LLM is down
    world.given_the_llm(RuleLLM(failing=CONFLICTING + ("Termination For Convenience",)))
    # When I run the check again
    world.when("post", "/SOW1/conflicts")
    # Then the failure is reported honestly, not as "no conflicts"
    assert world.response.status_code == 502
    # And the previous results are still there
    world.when("get", "/SOW1/conflicts")
    assert world.conflict_clause_ids() == previous


def test_scenario_a_capped_check_says_so(world, monkeypatch):
    import backend.application.services.conflict_detection_service as svc
    # Given a SOW with more comparable clause pairs than one check covers
    world.given_an_msa_and_a_sow(linked=True)
    monkeypatch.setattr(svc, "MAX_PAIRS", 2)
    # When I run a conflict check
    world.when("post", "/SOW1/conflicts")
    # Then the result says it compared only part of the contract
    body = world.response.json()
    assert body["pairs_truncated"] is True and body["pairs_checked"] == 2


def test_scenario_another_tenant_cannot_see_or_link_my_contracts(world):
    # Given my linked and checked contracts
    world.given_an_msa_and_a_sow(linked=True)
    world.when("post", "/SOW1/conflicts")
    intruder = {"X-Tenant-ID": "other-tenant"}
    # When another tenant tries to read, check or link them
    # Then every request behaves as if the contracts do not exist
    assert world.when("get", "/SOW1/conflicts", headers=intruder).status_code == 404
    assert world.when("post", "/SOW1/conflicts", headers=intruder).status_code == 404
    assert world.when("put", "/SOW1/governing-contract", headers=intruder,
                      json={"governing_contract_id": "MSA1"}).status_code == 404
