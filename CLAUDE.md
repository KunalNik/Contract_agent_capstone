# CLAUDE.md

Read `HANDOVER.md` first. It has the full context: history, architecture, conventions, how to run, and next steps.

## Essentials

- **Branch:** work on `Project1`. Commit in logical groups and push.
- **Shell:** the owner uses Windows PowerShell. Use `$env:VAR="x"; cmd`, not `VAR=x cmd`.
- **Python:** always use the backend venv, never the system Python (3.14, which lacks the dependencies).
  - Windows: `backend\.venv\Scripts\python.exe`
  - Linux/macOS: `backend/.venv/bin/python`
  - Create or refresh it with `cd backend; uv sync`.
- **Tests (offline, required before every commit):** `backend\.venv\Scripts\python.exe -m pytest -q`. Add a regression test in `backend/tests/unit/` for every bug fix.
- **Frontend:** `cd frontend; npm run build` must pass.
- **Dependencies:** `uv add <pkg>` inside `backend/`, and commit `pyproject.toml` and `uv.lock` together.

## Rules (each one prevents a bug that was already fixed once)

- Chat models vs the chat agent:
  - Use `LLMManager.get_chat_model(name)` for guards, analysis and extraction.
  - `get_model_by_name` returns the LangGraph chat agent; use it only for `/api/run/`.
- Never connect to Neo4j or Gemini at import time. Use the lazy `graph` from `backend/shared/utils/contract_search_tool.py` and `embedding` from `gemini_embedding_service.py`.
- Tenant handling:
  - The tenant comes only from the identity: use `Depends(get_current_tenant)` or `current_tenant()`.
  - Never take it from the request body, query string or the LLM.
  - Every tenant-data Cypher query must filter by `tenant_id`.
- Every new route needs `dependencies=[Depends(requires_permission(...))]`. A test enforces this.
- Async and blocking code:
  - No bare `asyncio.run` in library code; use `run_coro_sync`.
  - Run heavy sync work in handlers via `await asyncio.to_thread(...)`.
  - Graphs with async nodes must use `ainvoke` or `astream`.
- Declare every LangGraph state key in its `TypedDict`; undeclared keys are silently dropped.
- Neo4j: use `vector.similarity.cosine`, never `gds.*`.
- Errors: add `except HTTPException: raise` before a generic `except`, and don't report failures as success or empty results.
- Naming: never create a `backend/mcp` package; it shadows the `mcp` SDK. Local helpers live in `backend/mcp_support/`.
- Never commit `.env` or secrets.
