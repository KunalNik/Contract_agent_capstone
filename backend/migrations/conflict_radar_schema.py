"""Schema for the Cross-Contract Conflict Radar.

New graph elements (created by the application, not here):
    (:Contract)-[:GOVERNED_BY {tenant_id, created_at}]->(:Contract)
    (:Clause)-[:CONFLICTS_WITH {tenant_id, contract_id, governing_contract_id, conflict_type,
                                severity, explanation, suggested_resolution,
                                verification_reason, model, detected_at}]->(:Clause)
    Contract.conflict_check_status / conflict_checked_at / conflict_count /
             conflict_pairs_checked / conflict_pairs_failed

Every statement is idempotent (IF NOT EXISTS), so re-running is always safe.
Applied automatically by backend/migrations/runner.py at application startup.
"""

ID = "2026_10_conflict_radar_indexes"

STATEMENTS = (
    # Conflict queries (and most others) look contracts up by file id within a tenant
    "CREATE INDEX contract_file_tenant IF NOT EXISTS FOR (c:Contract) ON (c.file_id, c.tenant_id)",
    # Stored conflicts are read and replaced per (tenant, contract)
    "CREATE INDEX conflicts_with_contract IF NOT EXISTS "
    "FOR ()-[r:CONFLICTS_WITH]-() ON (r.tenant_id, r.contract_id)",
)
