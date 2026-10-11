"""Seed data for manual testing and demos. Idempotent: safe to run repeatedly.

Use cases covered (Cross-Contract Conflict Radar):
  * SEED_SOW_001 is governed by SEED_MSA_001 and has three planted conflicts
    (payment period, liability cap, governing law) and one consistent clause
    (termination notice) that must NOT be reported.
  * SEED_SOW_002 has no governing contract: a conflict check returns 409.

Seeded clauses carry no embeddings, so candidates are paired by clause type.
Every seeded node has ``seed: true`` so ``remove_seed_data`` can clean up.
Re-running ``seed`` also resets the demo: links, stored conflicts and check status go back to the
starting state, so manual test cases can be repeated.

Run:   python -m backend.migrations.runner seed   [--tenant default-tenant]
Undo:  python -m backend.migrations.runner unseed [--tenant default-tenant]
"""
from typing import Any, Dict, List

from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

SEED_CONTRACTS: List[Dict[str, Any]] = [
    {
        "file_id": "SEED_MSA_001",
        "name": "Seed - Master Services Agreement.pdf",
        "contract_type": "Service",
        "governed_by": None,
        "clauses": [
            ("Payment Terms", "Client shall pay all undisputed invoices within thirty (30) days of receipt."),
            ("Cap On Liability", "Each party's aggregate liability under this Agreement shall not exceed the "
                                 "fees paid in the twelve (12) months preceding the claim."),
            ("Governing Law", "This Agreement shall be governed by the laws of the State of New York."),
            ("Termination For Convenience", "Either party may terminate this Agreement for convenience on "
                                            "sixty (60) days' written notice."),
        ],
    },
    {
        "file_id": "SEED_SOW_001",
        "name": "Seed - Statement of Work 1.pdf",
        "contract_type": "Service",
        "governed_by": "SEED_MSA_001",
        "clauses": [
            ("Payment Terms", "Client shall pay each invoice issued under this SOW within ninety (90) days "
                              "of receipt."),
            ("Cap On Liability", "Supplier's liability for the services performed under this SOW shall be "
                                 "unlimited."),
            ("Governing Law", "This SOW shall be governed by the laws of the State of California."),
            ("Termination For Convenience", "This SOW may be terminated for convenience in accordance with "
                                            "the Agreement, on sixty (60) days' written notice."),
        ],
    },
    {
        "file_id": "SEED_SOW_002",
        "name": "Seed - Statement of Work 2 (unlinked).pdf",
        "contract_type": "Service",
        "governed_by": None,
        "clauses": [
            ("Payment Terms", "Client shall pay each invoice under this SOW within forty-five (45) days."),
        ],
    },
]

_UPSERT_CONTRACT = """
MERGE (c:Contract {file_id: $file_id, tenant_id: $tenant_id})
ON CREATE SET c.created_at = datetime()
SET c.seed = true,
    c.original_filename = $name,
    c.contract_type = $contract_type,
    c.summary = $name,
    c.full_text = $full_text
WITH c
UNWIND $clauses AS clause
MERGE (cl:Clause {id: clause.id})
SET cl.seed = true,
    cl.tenant_id = $tenant_id,
    cl.clause_type = clause.clause_type,
    cl.content = clause.content,
    cl.confidence = 1.0
MERGE (c)-[:CONTAINS_CLAUSE]->(cl)
"""

# Re-seeding restores each seed contract to its declared starting state: exactly the declared
# governing link (or none), no stored conflicts and no conflict-check status.
_RESET = """
MATCH (c:Contract {file_id: $file_id, tenant_id: $tenant_id})
OPTIONAL MATCH (c)-[link:GOVERNED_BY]->()
DELETE link
WITH DISTINCT c
OPTIONAL MATCH ()-[r:CONFLICTS_WITH {tenant_id: $tenant_id, contract_id: $file_id}]->()
DELETE r
WITH DISTINCT c
REMOVE c.conflict_check_status, c.conflict_checked_at, c.conflict_count,
       c.conflict_pairs_checked, c.conflict_pairs_failed, c.conflict_pairs_truncated
"""

_LINK = """
MATCH (child:Contract {file_id: $file_id, tenant_id: $tenant_id})
MATCH (parent:Contract {file_id: $governed_by, tenant_id: $tenant_id})
MERGE (child)-[link:GOVERNED_BY]->(parent)
ON CREATE SET link.created_at = datetime()
SET link.tenant_id = $tenant_id
"""

_REMOVE = """
MATCH (n)
WHERE (n:Contract OR n:Clause) AND n.seed = true AND n.tenant_id = $tenant_id
DETACH DELETE n
"""


def seed_data(graph, tenant_id: str) -> None:
    for contract in SEED_CONTRACTS:
        clauses = [
            {"id": f"{tenant_id}:{contract['file_id']}_clause_{i}", "clause_type": ctype, "content": text}
            for i, (ctype, text) in enumerate(contract["clauses"])
        ]
        graph.query(_UPSERT_CONTRACT, {
            "file_id": contract["file_id"], "tenant_id": tenant_id, "name": contract["name"],
            "contract_type": contract["contract_type"],
            "full_text": "\n\n".join(text for _, text in contract["clauses"]),
            "clauses": clauses,
        })
    for contract in SEED_CONTRACTS:
        graph.query(_RESET, {"file_id": contract["file_id"], "tenant_id": tenant_id})
        if contract["governed_by"]:
            graph.query(_LINK, {"file_id": contract["file_id"], "governed_by": contract["governed_by"],
                                "tenant_id": tenant_id})
    logger.info(f"Seeded {len(SEED_CONTRACTS)} contracts for tenant {tenant_id}")


def remove_seed_data(graph, tenant_id: str) -> None:
    graph.query(_REMOVE, {"tenant_id": tenant_id})
    logger.info(f"Removed seed data for tenant {tenant_id}")
