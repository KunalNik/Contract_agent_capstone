"""Test doubles for the Cross-Contract Conflict Radar (shared by TDD and BDD tests)."""
import json
import re
from typing import Dict, Iterable, List, Optional, Tuple

from langchain_core.messages import AIMessage

GENERIC = {"unknown", "general", "other", ""}


class RuleLLM:
    """Deterministic chat model: answers by clause type, safe under concurrent calls.

    - ``conflicting``: clause types the judge flags as conflicts
    - ``rejected``:    flagged types the verifier rejects (false positives)
    - ``failing``:     types whose judgement raises (LLM outage)
    """

    def __init__(self, conflicting: Iterable[str] = (), rejected: Iterable[str] = (),
                 failing: Iterable[str] = (), severity: str = "HIGH", conflict_type: str = "inconsistent_timeline"):
        self.conflicting, self.rejected, self.failing = set(conflicting), set(rejected), set(failing)
        self.severity, self.conflict_type = severity, conflict_type
        self.prompts: List[str] = []
        self.tags: List[str] = []

    def with_config(self, **kwargs):
        self.tags.extend(kwargs.get("tags", []))
        return self

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        clause_type = re.search(r"SUBORDINATE CONTRACT CLAUSE \(([^)]*)\)", prompt).group(1)
        if clause_type in self.failing:
            raise RuntimeError("LLM unavailable")
        if "FINDING (" in prompt:  # verification pass
            confirmed = clause_type not in self.rejected
            return AIMessage(content=json.dumps({"confirmed": confirmed, "reason": f"checked {clause_type}"}))
        conflict = clause_type in self.conflicting
        return AIMessage(content=json.dumps({
            "conflict": conflict, "conflict_type": self.conflict_type, "severity": self.severity,
            "explanation": f"{clause_type} terms differ", "suggested_resolution": f"Align {clause_type}",
        }))


class FakeConflictStore:
    """In-memory answers for every ConflictRepository query, installed on ``fake_graph``.

    contracts: {(tenant, file_id): display name}
    clauses:   {(tenant, file_id): [(clause_id, clause_type, content), ...]}
    links:     {(tenant, child_file_id): parent_file_id}
    """

    def __init__(self, fake_graph, contracts: Dict[Tuple[str, str], str],
                 clauses: Dict[Tuple[str, str], List[Tuple[str, str, str]]],
                 links: Optional[Dict[Tuple[str, str], str]] = None):
        self.contracts, self.clauses = contracts, clauses
        self.links = dict(links or {})
        self.conflicts: Dict[Tuple[str, str], List[dict]] = {}
        self.status: Dict[Tuple[str, str], dict] = {}
        fake_graph.handlers.extend([
            (r"OPTIONAL MATCH \(child\)-\[old:GOVERNED_BY\]", self._link),
            (r"WHERE r\.governing_contract_id <> \$governing_contract_id", self._clear_other_parents),
            (r"RETURN c\.file_id AS id", self._exists),
            (r"RETURN parent\.file_id AS contract_id", self._governing),
            (r"vector\.similarity\.cosine", self._pairs),
            (r"SET child\.conflict_check_status", self._save),
            (r"c\.conflict_check_status AS status", self._results),
        ])
        self.saves = 0

    # ---- linking
    def _link(self, p):
        child, parent = (p["tenant_id"], p["contract_id"]), (p["tenant_id"], p["governing_contract_id"])
        if child not in self.contracts or parent not in self.contracts:
            return []
        self.links[child] = p["governing_contract_id"]
        return [{"contract_id": p["contract_id"]}]

    def _clear_other_parents(self, p):
        key = (p["tenant_id"], p["contract_id"])
        self.conflicts[key] = [c for c in self.conflicts.get(key, [])
                               if c["governing_contract_id"] == p["governing_contract_id"]]
        return []

    def _exists(self, p):
        return [{"id": p["contract_id"]}] if (p["tenant_id"], p["contract_id"]) in self.contracts else []

    def _governing(self, p):
        parent = self.links.get((p["tenant_id"], p["contract_id"]))
        return [{"contract_id": parent, "name": self.contracts[(p["tenant_id"], parent)]}] if parent else []

    # ---- candidates: same (non-generic) clause type, mirroring the Cypher
    def _pairs(self, p):
        tenant = p["tenant_id"]
        parent = self.links.get((tenant, p["contract_id"]))
        if not parent:
            return []
        rows = [
            {"clause_id": a_id, "clause_type": a_type, "content": a_text,
             "governing_clause_id": b_id, "governing_clause_type": b_type, "governing_content": b_text,
             "similarity": None, "same_type": True}
            for a_id, a_type, a_text in self.clauses.get((tenant, p["contract_id"]), [])
            for b_id, b_type, b_text in self.clauses.get((tenant, parent), [])
            if a_type.lower() == b_type.lower() and a_type.lower() not in GENERIC
        ]
        return rows[: p["max_pairs"]]

    # ---- results: one atomic statement replaces conflicts and records the run
    def _save(self, p):
        tenant = p["tenant_id"]
        if (tenant, p["contract_id"]) not in self.contracts:
            return []
        self.saves += 1
        self.status[(tenant, p["contract_id"])] = {
            "status": p["status"], "pairs_checked": p["pairs_checked"], "pairs_failed": p["pairs_failed"],
            "pairs_truncated": p["pairs_truncated"]}
        by_id = {cid: (ctype, text) for clauses in self.clauses.values() for cid, ctype, text in clauses}
        self.conflicts[(tenant, p["contract_id"])] = [
            {**{k: f[k] for k in ("conflict_type", "severity", "explanation", "suggested_resolution",
                                  "verification_reason")},
             "governing_contract_id": p["governing_contract_id"], "detected_at": None,
             "clause": {"clause_id": f["clause_id"], "clause_type": by_id[f["clause_id"]][0],
                        "content": by_id[f["clause_id"]][1]},
             "governing_clause": {"clause_id": f["governing_clause_id"],
                                  "clause_type": by_id[f["governing_clause_id"]][0],
                                  "content": by_id[f["governing_clause_id"]][1]}}
            for f in p["findings"]
        ]
        return [{"stored": len(p["findings"])}]

    def _results(self, p):
        key = (p["tenant_id"], p["contract_id"])
        if key not in self.contracts:
            return []
        status = self.status.get(key, {})
        return [{"status": status.get("status"), "checked_at": None,
                 "pairs_checked": status.get("pairs_checked"), "pairs_failed": status.get("pairs_failed"),
                 "pairs_truncated": status.get("pairs_truncated"),
                 "conflicts": [{k: v for k, v in c.items() if k != "governing_contract_id"}
                               for c in self.conflicts.get(key, [])]}]


def msa_sow_store(fake_graph, tenant: str = "default-tenant", linked: bool = True) -> FakeConflictStore:
    """An MSA and a SOW with three conflicting clause types and one consistent one."""
    msa = [("M1", "Payment Terms", "Pay within 30 days."),
           ("M2", "Cap On Liability", "Liability capped at 12 months of fees."),
           ("M3", "Governing Law", "Laws of New York."),
           ("M4", "Termination For Convenience", "60 days' notice.")]
    sow = [("S1", "Payment Terms", "Pay within 90 days."),
           ("S2", "Cap On Liability", "Liability is unlimited."),
           ("S3", "Governing Law", "Laws of California."),
           ("S4", "Termination For Convenience", "60 days' notice, per the Agreement."),
           ("S5", "unknown", "Miscellaneous text.")]
    return FakeConflictStore(
        fake_graph,
        contracts={(tenant, "MSA1"): "msa.pdf", (tenant, "SOW1"): "sow.pdf", (tenant, "MSA2"): "msa2.pdf"},
        clauses={(tenant, "MSA1"): msa, (tenant, "SOW1"): sow,
                 (tenant, "MSA2"): [("N1", "Payment Terms", "Pay within 90 days.")]},
        links={(tenant, "SOW1"): "MSA1"} if linked else {},
    )
