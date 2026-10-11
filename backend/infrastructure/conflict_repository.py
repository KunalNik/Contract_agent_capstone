"""Neo4j persistence for the Cross-Contract Conflict Radar.

Graph shape:
    (child:Contract)-[:GOVERNED_BY]->(parent:Contract)
    (childClause:Clause)-[:CONFLICTS_WITH {contract_id, tenant_id, ...}]->(parentClause:Clause)

Clauses hang off a contract either directly (embedding pipeline) or through a
Section (section/clause extraction), and use either ``clause_id`` or ``id``;
every query here handles both. All queries are scoped to the caller's tenant.
"""
from typing import Any, Dict, List, Optional

from backend.domain.contracts.conflicts import ClausePair, ClauseRef, ConflictCheckResult
from backend.shared.utils.contract_search_tool import graph as shared_graph
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

# Clause types too generic to pair on type alone
_GENERIC_CLAUSE_TYPES = ["unknown", "general", "other", ""]

_CLAUSES_OF = "-[:HAS_SECTION|CONTAINS_CLAUSE*1..2]->"


class ConflictRepository:
    def __init__(self, graph=None):
        self.graph = graph or shared_graph

    # ------------------------------------------------------------- linking
    def contract_exists(self, contract_id: str, tenant_id: str) -> bool:
        rows = self.graph.query(
            "MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id}) RETURN c.file_id AS id",
            {"contract_id": contract_id, "tenant_id": tenant_id},
        )
        return bool(rows)

    def link_governing_contract(self, contract_id: str, governing_contract_id: str, tenant_id: str) -> bool:
        """Make ``governing_contract_id`` the single governing contract of ``contract_id``.

        Re-linking replaces the previous link and clears results computed
        against the old governing contract. Returns False if either contract
        does not exist in this tenant.
        """
        rows = self.graph.query(
            """
            MATCH (child:Contract {file_id: $contract_id, tenant_id: $tenant_id})
            MATCH (parent:Contract {file_id: $governing_contract_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (child)-[old:GOVERNED_BY]->(previous:Contract)
            WHERE previous <> parent
            DELETE old
            WITH DISTINCT child, parent
            MERGE (child)-[link:GOVERNED_BY]->(parent)
            ON CREATE SET link.created_at = datetime()
            SET link.tenant_id = $tenant_id
            RETURN child.file_id AS contract_id
            """,
            {"contract_id": contract_id, "governing_contract_id": governing_contract_id, "tenant_id": tenant_id},
        )
        if rows:
            self._clear_results_for_other_parents(contract_id, governing_contract_id, tenant_id)
        return bool(rows)

    def _clear_results_for_other_parents(self, contract_id: str, governing_contract_id: str, tenant_id: str) -> None:
        self.graph.query(
            """
            MATCH ()-[r:CONFLICTS_WITH {tenant_id: $tenant_id, contract_id: $contract_id}]->()
            WHERE r.governing_contract_id <> $governing_contract_id
            DELETE r
            """,
            {"contract_id": contract_id, "governing_contract_id": governing_contract_id, "tenant_id": tenant_id},
        )

    def get_governing_contract(self, contract_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        rows = self.graph.query(
            """
            MATCH (child:Contract {file_id: $contract_id, tenant_id: $tenant_id})
                  -[:GOVERNED_BY]->(parent:Contract {tenant_id: $tenant_id})
            RETURN parent.file_id AS contract_id,
                   coalesce(parent.original_filename, parent.file_id) AS name
            """,
            {"contract_id": contract_id, "tenant_id": tenant_id},
        )
        return dict(rows[0]) if rows else None

    # ------------------------------------------------------------- candidates
    def find_candidate_pairs(self, contract_id: str, tenant_id: str,
                             min_similarity: float, max_pairs: int) -> List[ClausePair]:
        """Clause pairs worth judging: same clause type, or semantically similar text.

        One row per clause pair (a clause with several CUAD classifications is
        not judged twice). Type matches rank first, then by similarity, capped
        at ``max_pairs`` to bound LLM cost.
        """
        rows = self.graph.query(
            f"""
            MATCH (child:Contract {{file_id: $contract_id, tenant_id: $tenant_id}})
                  -[:GOVERNED_BY]->(parent:Contract {{tenant_id: $tenant_id}})
            MATCH (child){_CLAUSES_OF}(a:Clause)
            MATCH (parent){_CLAUSES_OF}(b:Clause)
            OPTIONAL MATCH (a)-[:CLASSIFIED_AS]->(at:ClauseType)
            OPTIONAL MATCH (b)-[:CLASSIFIED_AS]->(bt:ClauseType)
            WITH a, b,
                 coalesce(at.cuad_type, a.clause_type, '') AS a_type,
                 coalesce(bt.cuad_type, b.clause_type, '') AS b_type,
                 CASE WHEN a.embedding IS NOT NULL AND b.embedding IS NOT NULL
                      THEN vector.similarity.cosine(a.embedding, b.embedding) END AS similarity
            WITH a, b, a_type, b_type, similarity,
                 (toLower(a_type) = toLower(b_type) AND NOT toLower(a_type) IN $generic_types) AS same_type
            WHERE same_type OR similarity >= $min_similarity
            WITH a, b, similarity,
                 collect(a_type)[0] AS clause_type, collect(b_type)[0] AS governing_clause_type,
                 max(CASE WHEN same_type THEN 1 ELSE 0 END) AS type_match
            RETURN coalesce(a.clause_id, a.id) AS clause_id, clause_type, a.content AS content,
                   coalesce(b.clause_id, b.id) AS governing_clause_id, governing_clause_type,
                   b.content AS governing_content, type_match
            ORDER BY type_match DESC, coalesce(similarity, 0.0) DESC
            LIMIT $max_pairs
            """,
            {"contract_id": contract_id, "tenant_id": tenant_id, "min_similarity": min_similarity,
             "max_pairs": max_pairs, "generic_types": _GENERIC_CLAUSE_TYPES},
        )
        return [
            ClausePair(
                clause=ClauseRef(r["clause_id"], r["clause_type"], r["content"] or ""),
                governing_clause=ClauseRef(r["governing_clause_id"], r["governing_clause_type"],
                                           r["governing_content"] or ""),
            )
            for r in rows
            if r.get("clause_id") and r.get("governing_clause_id")
        ]

    # ------------------------------------------------------------- results
    def save_results(self, result: ConflictCheckResult, tenant_id: str, model: str) -> None:
        """Replace this contract's stored conflicts with ``result`` and record the run.

        A single statement, so it runs in one transaction: a failure part-way
        can never leave the previous results deleted without new ones stored.
        """
        rows = self.graph.query(
            f"""
            MATCH (child:Contract {{file_id: $contract_id, tenant_id: $tenant_id}})
            OPTIONAL MATCH ()-[old:CONFLICTS_WITH {{tenant_id: $tenant_id, contract_id: $contract_id}}]->()
            DELETE old
            WITH DISTINCT child
            SET child.conflict_check_status = $status,
                child.conflict_checked_at = datetime(),
                child.conflict_count = size($findings),
                child.conflict_pairs_checked = $pairs_checked,
                child.conflict_pairs_failed = $pairs_failed,
                child.conflict_pairs_truncated = $pairs_truncated
            WITH child
            OPTIONAL MATCH (child)-[:GOVERNED_BY]->(parent:Contract {{file_id: $governing_contract_id, tenant_id: $tenant_id}})
            UNWIND $findings AS f
            MATCH (child){_CLAUSES_OF}(a:Clause) WHERE coalesce(a.clause_id, a.id) = f.clause_id
            MATCH (parent){_CLAUSES_OF}(b:Clause) WHERE coalesce(b.clause_id, b.id) = f.governing_clause_id
            WITH DISTINCT a, b, f
            CREATE (a)-[:CONFLICTS_WITH {{
                tenant_id: $tenant_id,
                contract_id: $contract_id,
                governing_contract_id: $governing_contract_id,
                conflict_type: f.conflict_type,
                severity: f.severity,
                explanation: f.explanation,
                suggested_resolution: f.suggested_resolution,
                verification_reason: f.verification_reason,
                model: $model,
                detected_at: datetime()
            }}]->(b)
            RETURN count(*) AS stored
            """,
            {"contract_id": result.contract_id, "tenant_id": tenant_id,
             "governing_contract_id": result.governing_contract_id, "model": model,
             "status": result.status, "pairs_checked": result.pairs_checked,
             "pairs_failed": result.pairs_failed, "pairs_truncated": result.pairs_truncated,
             "findings": [
                 {"clause_id": f.pair.clause.clause_id,
                  "governing_clause_id": f.pair.governing_clause.clause_id,
                  "conflict_type": f.conflict_type, "severity": f.severity,
                  "explanation": f.explanation, "suggested_resolution": f.suggested_resolution,
                  "verification_reason": f.verification_reason}
                 for f in result.findings
             ]},
        )
        stored = rows[0]["stored"] if rows else 0
        if stored != len(result.findings):
            logger.warning(f"Stored {stored} of {len(result.findings)} conflicts for contract "
                           f"{result.contract_id}; clauses may have changed during the check")
        logger.info(f"Stored conflict check for contract {result.contract_id}: {stored} conflicts")

    def get_results(self, contract_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Last run's summary and stored conflicts, or None if the contract doesn't exist."""
        rows = self.graph.query(
            """
            MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (a:Clause)-[r:CONFLICTS_WITH {tenant_id: $tenant_id, contract_id: $contract_id}]->(b:Clause)
            WITH c, a, r, b ORDER BY CASE r.severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END
            RETURN c.conflict_check_status AS status,
                   c.conflict_checked_at AS checked_at,
                   c.conflict_pairs_checked AS pairs_checked,
                   c.conflict_pairs_failed AS pairs_failed,
                   c.conflict_pairs_truncated AS pairs_truncated,
                   collect(CASE WHEN r IS NOT NULL THEN {
                        conflict_type: r.conflict_type,
                        severity: r.severity,
                        explanation: r.explanation,
                        suggested_resolution: r.suggested_resolution,
                        verification_reason: r.verification_reason,
                        detected_at: r.detected_at,
                        clause: {clause_id: coalesce(a.clause_id, a.id), clause_type: a.clause_type, content: a.content},
                        governing_clause: {clause_id: coalesce(b.clause_id, b.id), clause_type: b.clause_type, content: b.content}
                   } END) AS conflicts
            """,
            {"contract_id": contract_id, "tenant_id": tenant_id},
        )
        return dict(rows[0]) if rows else None
