"""Automated, idempotent schema migrations.

Each registered migration runs once per database; applied ids are recorded as
(:SchemaMigration {id}) nodes. Migration statements are themselves idempotent,
so a crash mid-migration (or two instances starting together) is safe: the
next run simply re-applies it.

The app applies pending migrations at startup (see ``main.py`` lifespan).
Manual use:
    python -m backend.migrations.runner migrate
    python -m backend.migrations.runner seed   [--tenant default-tenant]
    python -m backend.migrations.runner unseed [--tenant default-tenant]
"""
import argparse
import sys
from typing import List, Sequence, Tuple

from backend.migrations import conflict_radar_schema
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

# Ordered registry: (id, statements). Append new migrations; never reorder or edit applied ones.
MIGRATIONS: Sequence[Tuple[str, Sequence[str]]] = (
    (conflict_radar_schema.ID, conflict_radar_schema.STATEMENTS),
)

_BOOTSTRAP = "CREATE CONSTRAINT schema_migration_id IF NOT EXISTS FOR (m:SchemaMigration) REQUIRE m.id IS UNIQUE"


def _default_graph():
    from backend.shared.utils.contract_search_tool import graph
    return graph


def apply_pending(graph=None) -> List[str]:
    """Apply migrations not yet recorded in the database; returns the ids applied."""
    graph = graph or _default_graph()
    graph.query(_BOOTSTRAP)
    applied = {row["id"] for row in graph.query("MATCH (m:SchemaMigration) RETURN m.id AS id")}

    newly_applied = []
    for migration_id, statements in MIGRATIONS:
        if migration_id in applied:
            continue
        logger.info(f"Applying schema migration {migration_id}")
        for statement in statements:
            graph.query(statement)
        graph.query("MERGE (m:SchemaMigration {id: $id}) ON CREATE SET m.applied_at = datetime()",
                    {"id": migration_id})
        newly_applied.append(migration_id)
    logger.info(f"Schema migrations up to date ({len(newly_applied)} applied now)")
    return newly_applied


def apply_pending_on_startup() -> None:
    """Startup hook: never let an unreachable database stop the app from starting."""
    try:
        apply_pending()
    except Exception as e:
        logger.error(f"Schema migrations not applied (will retry on next startup): {e}")


def main(argv=None) -> int:
    from backend.migrations.seed_data import remove_seed_data, seed_data
    from backend.shared.utils.request_context import DEFAULT_TENANT

    parser = argparse.ArgumentParser(description="Schema migrations and seed data")
    parser.add_argument("command", choices=["migrate", "seed", "unseed"])
    parser.add_argument("--tenant", default=DEFAULT_TENANT, help="tenant for seed/unseed")
    args = parser.parse_args(argv)

    graph = _default_graph()
    if args.command == "migrate":
        apply_pending(graph)
    elif args.command == "seed":
        apply_pending(graph)
        seed_data(graph, args.tenant)
    else:
        remove_seed_data(graph, args.tenant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
