# Project Handover: Contract Agent Capstone

This file gives a new Claude Code session (or developer) full context on the project, the work done so far, how to run and test it, the conventions the code now follows, and what to do next. Read it end to end before changing code.

- **Repository:** `github.com/KunalNik/Contract_agent_capstone`
- **Working branch:** `Project1` (all fixes live here; `main` does not have them yet)
- **Owner's machine:** Windows, PowerShell, repo at `K:\Agentic AI Course Projects\Contract_agent_capstone`
- **Last verified state:** commit `11ea4c0` plus this handover. 80 offline tests pass, `npm run build` passes, and the MCP server starts and lists 4 tools.

---

## 1. What the project is

**What it does:** A multi-agent contract intelligence platform (a legal AI capstone). Users upload contract PDFs. The system:

1. extracts and stores them in a Neo4j graph;
2. analyses them with a pipeline of agents: clause extraction, policy compliance, risk scoring, CUAD deviation, jurisdiction and precedent analysis, and redline suggestions;
3. supports multi-level semantic search;
4. lets users chat with an LLM agent that searches the contracts;
5. manages company policy playbooks;
6. exposes tools to external AI clients through an MCP server.

**Stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, LangChain and LangGraph |
| Database | Neo4j 5.x (graph and vectors; the `vector.similarity.cosine` function is required) |
| LLMs | Gemini by default (`gemini-2.5-flash`); OpenAI, Anthropic and Mistral are optional |
| Embeddings | Gemini `gemini-embedding-001`, 1536 dimensions |
| Frontend | React 19, TypeScript, Vite, Tailwind |
| Tracing | Arize Phoenix (optional) |
| Cache | Redis (optional; in-memory fallback) |
| Dependencies | `uv` for Python (`backend/pyproject.toml` and `backend/uv.lock`), npm for the frontend |

---

## 2. Owner's environment and immediate state

- **OS and shell:** Windows with **PowerShell**. Bash syntax such as `VAR=value cmd` does **not** work.
  - Setting an environment variable looks like `$env:VAR="value"; cmd`.
  - Paths use backslashes: `backend\.venv\Scripts\python.exe`.
- **Python:**
  - The system Python is **3.14** and does **not** have the project's dependencies.
  - The project needs Python **3.12**. `uv sync` downloads it automatically.
  - Always run backend code with `backend\.venv\Scripts\python.exe` (Windows) or `backend/.venv/bin/python` (Linux/macOS).
- **uv:** installed with `pip install uv` (version 0.12.x).
- **Pending git issue (resolve this first):**
  - The owner's local `docker-compose.yml` has uncommitted edits, so `git pull origin Project1` failed with "Your local changes ... would be overwritten".
  - Recommended resolution:
    ```powershell
    Copy-Item docker-compose.yml docker-compose.mine.yml
    git checkout -- docker-compose.yml
    git pull origin Project1
    git diff --no-index docker-compose.yml docker-compose.mine.yml
    ```
  - If the diff shows only line endings (CRLF), delete `docker-compose.mine.yml`.
  - If it shows real settings (for example Neo4j Aura credentials), move secrets into `.env` and port any structural change into the new `docker-compose.yml`.
  - Never commit secrets.
- **Already done on the owner's machine:** `python scripts/update_contract_types.py` succeeded.
- **Owner's next steps after the pull:**
  1. `cd backend; uv sync; cd ..`
  2. Run tests.
  3. Run the app (Docker or local).
  4. Run the MCP server.

---

## 3. History of the work

### 3.1 Audits (reports are in the repo root)

- **`BUG_REPORT.md`:** second-pass bug audit. It corrected 6 claims from a first pass and added about 43 findings.
- **`AUDIT_REPORT.md`:** prioritised report with six sections:
  1. executive summary
  2. inventory
  3. broken features (with repro, evidence, root cause, plan and effort)
  4. security
  5. reliability and test gaps
  6. roadmap
  - The top of the report has a fix-status note; the end lists remaining limitations and a data migration.
- **`scripts/repro_bugs.py`:** offline repro harness that stubs Neo4j and Gemini. It originally reproduced 23 of 23 bugs and now reports **0/23**. Run it with:
  ```
  PYTHONPATH=. backend/.venv/bin/python scripts/repro_bugs.py
  ```
  On Windows: `$env:PYTHONPATH="."; backend\.venv\Scripts\python.exe scripts\repro_bugs.py`

### 3.2 Fix commits on `Project1` (oldest first)

| Commit | Scope |
|---|---|
| `6bcb3ad` | Startup, chat streaming, governance guards, RBAC/JWT, CORS, tracing, offline test harness |
| `70723c5` | Contract intelligence pipeline |
| `fd7d657` | Upload paths, enhanced PDF agent, chunk linkage, date validation |
| `59f0d27` | Policies, patterns, supervisor, search, MCP, feedback, audit, cache |
| `c328c0c` | Security config, frontend build (38 TypeScript errors to 0), Docker, CI, lockfile |
| `76d9ad0` | Reports updated with fix status and remaining limitations |
| `11ea4c0` | MCP server couldn't start (`backend/mcp` shadowed the `mcp` SDK); README Windows commands |

### 3.3 Most important bugs that were fixed

Keep these in mind so they are not reintroduced.

**Chat and guards**

- **Chat always failed.** Two causes:
  - `InjectionValidator` used an undefined variable.
  - `IntentValidator` had `except Exception:` followed by a reference to `e`.

  Both raised inside the SSE generator, so the stream came back empty.
- **Guards failed open.** Every LLM guard (safety, intent, hallucination) called `.invoke(str)` on the **LangGraph chat agent** instead of a chat model, so each check threw an error and returned "safe".
- **Topic and keyword guards blocked normal questions**, such as "What are the payment terms?" and "administrative fees".
- **Chat history grew exponentially.** The server sends the full history; the frontend appended it instead of replacing it.
- **The LLM could choose `tenant_id`** in the chat search tools, and could append **raw Cypher** (`cypher_aggregation`). Both have been removed.

**Contract analysis**

- **`ClauseDetectorTool` returned 2 hardcoded clauses** for every contract. It now uses the LLM, with keyword heuristics as the fallback.
- **The `model=` parameter had no effect**: the orchestrator never used the LLM.
- **`asyncio.run` inside a running event loop.** The non-planning analysis returned empty results for contracts over 10k characters.
- **Failed analyses were stored as "completed"** with a zero risk score.
- **The planning path crashed on a fresh server** (`workflow_tracker` start time was `None`).

**Uploads**

- The duplicate-upload check crashed with a `KeyError` and matched filenames across tenants.
- Enhanced upload called sync `.invoke()` on a graph that has an async node, so it always failed.
- The enhanced PDF agent called `CompiledStateGraph.get_node()`, which doesn't exist, so it could not be built.

**Policies**

- Policy upload failed in 6 independent places:
  - it called `SupervisorAgent()` without its required arguments;
  - `AuditEvent` was undefined;
  - `PolicyChunkingStrategy` was abstract and could not be instantiated;
  - the content validator read a key that never existed;
  - the rule validator was chained before any rules were extracted;
  - it called `asyncio.run` inside the event loop.

**Search**

- The clause, section and relationship search endpoints returned `null`.
- Search had no tenant filter.

**Other subsystems**

- **Patterns API:** called `.process()`, which doesn't exist (the method is `.execute()`).
- **Supervisor:**
  - inputs were never passed to the agents;
  - coroutines were never awaited;
  - agent IDs didn't match;
  - status lookups always failed.
- **MCP:** `fetch_contract_metadata` didn't await an async call.
- **Auth and startup:**
  - RBAC defaulted to ADMIN, including in production;
  - the app could not start without a live Neo4j and a Google API key (connections were made at import time).

---

## 4. Repository layout

```
backend/                     FastAPI app (package name `backend`; run from repo root with PYTHONPATH=.)
  main.py                    App, routers, CORS, /api/health, chat SSE (/api/run/), PII stream redactor
  llm_manager.py             Model registry; get_chat_model() vs get_model_by_name(); shared manager
  contract_chat_agent.py     LangGraph tool-calling chat agent (ContractSearch + EnhancedContractSearch tools)
  mcp_server.py              Standalone MCP server (stdio), 4 tools
  mcp_support/decorators.py  mcp_tool_wrapper (tracing, tenant check, MCP_TENANT_ID pinning)
  api/                       Routers:
    document_upload.py       /api/documents/upload, /upload-stream, /status
    enhanced_document_upload.py  /api/documents/enhanced/upload, /embedding-status/{id}
    contract_intelligence.py /api/intelligence/contracts/{id}/analyze|status, /batch-analyze, /dashboard/summary, /models
    enhanced_contract_search.py  /api/contracts/search/enhanced|clauses|sections|relationships|clause-types|section-types
    policy_api.py            /api/policies/upload, /tenant, /{id}, /compliance/check, /search, /applicable/{type}, DELETE /{id}
    patterns_api.py          /api/patterns/analyze|react|chain-of-thought|advanced-rag|capabilities
    supervisor_api.py        /api/supervisor/workflow/execute, /workflow/{id}/status
    feedback_api.py          /api/feedback/* (legal decisions, learned patterns, analytics)
    monitoring_api.py        /api/monitoring/* (performance, health, alerts, cache, batch)
    audit_api.py             /api/audit/trail/{id}, /errors/statistics, /errors/recent
    routes/debug.py          /debug/* (development only, tenant-scoped)
  agents/
    contract_intelligence_agents.py  IntelligenceOrchestrator (LangGraph workflow + planning path)
    intelligence_tools.py    ClauseDetectorTool (LLM + heuristic), PolicyChecker, RiskCalculator, RedlineGenerator
    planning/                PlanningAgent + PlanExecutionEngine
    patterns/                ReACT, Chain-of-Thought, Advanced RAG, PatternOrchestrator
    supervisor/              SupervisorAgent, adapters, circuit breaker, retry, quality
    pdf_processing_agent.py  build_pdf_nodes() + basic PDF graph (extract -> analyze -> store)
    enhanced_pdf_processing_agent.py  + sections -> clauses -> CUAD classification
    policy_agents.py, policy_workflow_orchestrator.py  Policy chunk/extract/compliance
    cuad_mitigation_tools.py (phase 1), enhanced_cuad_tools.py (phase 2), optimized_cuad_tools.py (phase 3)
    feedback_learning_system.py  Legal decisions -> learned patterns
    chunking_agent.py        Chunking orchestration
  application/services/      document_processing_service, enhanced_document_processing_service,
                             embedding_pipeline (shared), contract_intelligence_service, policy_service
  governance/                rbac.py (auth), prompt_guard, output_guard, pii_engine, llm_judge, validators/
  infrastructure/            Neo4j repositories, audit_logger, error_tracker, text_extractors, chunking/, caches
  shared/utils/              lazy.py (LazyProxy), request_context.py (tenant), async_utils.py (run_coro_sync),
                             contract_search_tool.py (shared `graph`), gemini_embedding_service.py (`embedding`), utils.py
  shared/cache/redis_cache.py, shared/monitoring/performance_monitor.py
  migrations/, embeddings/, domain/, factories/, validation/
  tests/unit/                OFFLINE regression suite (80 tests) - conftest stubs Neo4j + Gemini
  tests/*.py                 Older tests; test_rbac_unit + test_pii_unit are included in pytest
frontend/                    React app: pages/, components/features/{contracts,intelligence,search,...}, services/
scripts/                     update_contract_types.py, upload_cli.py, import_to_aura.py, repro_bugs.py, ...
training/                    QLoRA teacher/student fine-tuning pipeline (RunPod); not touched in this work
tests/                       Legacy integration scripts needing live services (not in pytest; not updated)
docs/, Documentation - Dwarak/, research/   Design docs, notebooks
.github/workflows/ci.yml     CI: backend pytest + frontend build
pytest.ini                   testpaths = backend/tests/unit + 2 legacy unit files; pythonpath = . backend/tests/unit
docker-compose.yml           neo4j, backend, ui, phoenix, redis (profile "cache")
```

---

## 5. Architecture and key conventions

Follow these; they fix the classes of bugs listed above.

### 5.1 LLM access (`backend/llm_manager.py`)

- **`LLMManager.get_chat_model(name)`** returns the **raw chat model** (`.invoke("text")` works). Use it for guards, analysis, extraction and classification.
- **`LLMManager.get_model_by_name(name)`** returns the **LangGraph tool-calling chat agent**. Use it **only** for `/api/run/` chat.
- `MODEL_REGISTRY`: `gpt-4o`, `gemini-2.5-pro`, `gemini-2.5-flash`, `claude-sonnet` (model from the `ANTHROPIC_MODEL` env var), `mistral-large`. A model loads only when its API key is set.
- A process-wide manager is available through `get_shared_llm_manager()`; `main.py`'s lifespan sets it.
- Route handlers get the manager from `request.app.state.llm_manager`.
- The frontend model dropdowns load their options from `/api/documents/status` (`available_models`). Don't hardcode model lists.

### 5.2 Database and embeddings (lazy)

- `backend/shared/utils/contract_search_tool.py` exposes `graph`, a `LazyProxy` around `Neo4jGraph`. It connects on first query, never at import.
- `gemini_embedding_service.embedding` is likewise lazy.
- **Never create `Neo4jGraph(...)` or the embedding client at module import time.** Import `graph` and `embedding` from those modules.
- Neo4j **5.x** is required. Use the built-in `vector.similarity.cosine`; **don't use the GDS plugin** (`gds.similarity.*`), which isn't available on Aura Free or community installs.
- `/api/health` reports database and LLM readiness without failing startup.

### 5.3 Tenancy and identity (`backend/governance/rbac.py`, `backend/shared/utils/request_context.py`)

- **Auth modes** (`auth_mode()`):
  - `jwt`: required when `ENVIRONMENT=production`. Header mode is refused in production even if configured.
    - Requests send `Authorization: Bearer <HS256 token>`, signed with `JWT_SECRET`.
    - The token carries claims `sub`, `role` and `tenant_id`.
    - `create_access_token(user_id, role, tenant_id)` issues tokens for scripts and tests.
  - `header` (development default):
    - Role comes from `X-User-Role`, defaulting to `DEV_DEFAULT_ROLE` (ADMIN).
    - Tenant comes from `X-Tenant-ID`, defaulting to `default-tenant`.
- **Roles:**

  | Role | Permissions |
  |---|---|
  | ADMIN | all |
  | LEGAL_REVIEWER | ANALYZE, UPLOAD, VIEW_REPORTS |
  | AUDITOR | VIEW_REPORTS, VIEW_AUDIT |
  | VIEWER | ANALYZE |

  The full permission set is UPLOAD, DELETE, ANALYZE, VIEW_REPORTS, MANAGE_POLICIES and VIEW_AUDIT.
- **Route protection:** use `dependencies=[Depends(requires_permission(Permission.X))]`. To get the tenant, use `tenant_id: str = Depends(get_current_tenant)` or `user: CurrentUser = Depends(get_current_user)`.
- **The tenant is never a query or body parameter**, and it is never chosen by the LLM.
  - `get_current_user` sets `tenant_id_var` (a context variable). Tools and services read it with `current_tenant()`.
  - `asyncio.to_thread` and `run_coro_sync` preserve context variables.
- **Every Cypher query that reads tenant data must filter by tenant**: `c.tenant_id = $tenant_id`, or match `(c:Contract {tenant_id: $tenant_id})`.
  - `Party` nodes are merged per tenant: `MERGE (p:Party {name, tenant_id})`.
- **Test guard:** `backend/tests/unit/test_rbac_modes.py::test_every_data_route_requires_authentication` fails if a new route lacks auth. Only static information routes are in `PUBLIC_ROUTES`.
- `AuditLogger.log_event` and `ErrorContext` default the tenant to the current request's tenant.

### 5.4 Async and blocking work

- Handlers are async. Run heavy synchronous work (the multi-agent analysis, the supervisor, search, guard LLM calls) with `await asyncio.to_thread(...)` so the event loop keeps serving requests.
- To call a coroutine from sync code, use `backend.shared.utils.async_utils.run_coro_sync(coro)`. **Never use bare `asyncio.run`** inside code that might run under FastAPI; it raises "cannot be called from a running event loop".
- LangGraph graphs that contain async nodes (the PDF agents' `store_contract`) must be run with `ainvoke` or `astream`, never `invoke`.
- LangGraph drops state keys that aren't declared in the `TypedDict`. Declare every key a node returns (see `agents/pdf_state.py` and `agents/intelligence_state.py`).
- `ProcessingResult` is a dataclass: use `getattr(result, "contract_id", None)`, not `.get(...)`.

### 5.5 Chat SSE protocol (`POST /api/run/`)

**Request body:** `{"model": "...", "prompt": "...", "history": "<JSON string list of message JSON>"}`

**Events:** each is `data: {"type": ..., "content": ...}`, where `type` is one of:

| Type | Meaning |
|---|---|
| `ai_message` | Answer text; PII is redacted during streaming at sentence boundaries |
| `tool_call` | The agent called a tool |
| `tool_message` | A tool returned output |
| `error` | Something failed or was blocked |
| `retract` | The client must remove the AI text already shown (the output guard blocked it) |
| `history` | The **full** conversation; the client must **replace** its stored history |
| `end` | Always sent, even on failure |

**Guard flow:**

1. `PromptGuard` runs the chain injection, PII, keyword, topic, intent.
2. The agent streams its answer.
3. `OutputGuard` runs the chain Llama-Guard-style safety, domain compliance, hallucination (checked against tool outputs), then PII redaction.

**Guard settings:**

- `GUARD_FAIL_CLOSED=true` makes an unavailable guard block the request instead of allowing it.
- `GUARD_MODEL` sets the guard model (default `gemini-2.5-flash`).
- The "Llama Guard" validator is Gemini prompted with the Llama Guard taxonomy.

### 5.6 Contract analysis pipeline

- **Entry point:** `ContractIntelligenceService.analyze_contract_by_id(contract_id, tenant_id, model, use_planning)`. It runs `analyze_contract_intelligence` on a worker thread.
- **Two paths in `IntelligenceOrchestrator.analyze_contract`:**
  - Planning (default): `PlanningAgent` creates a plan and `PlanExecutionEngine` executes it.
  - Traditional: a LangGraph workflow running extraction, pattern analysis (ReACT or CoT for longer contracts), policy check, risk, CUAD mitigation and redlines.
  - Both paths merge CUAD deviations into violations, so they produce consistent results.
- **Failure handling:**
  - A failed run sets `ContractIntelligence.status = "failed"`.
  - The API returns **502** with the reason.
  - The database records `last_analysis_status='failed'` and never overwrites a completed analysis.
- **CUAD tools, three tiers:** phase 3 (optimized, cached) falls back to phase 2 (enhanced), which falls back to phase 1.
  - Precedent data that comes from built-in samples is labelled `data_source: "illustrative_baseline"`.

### 5.7 Upload pipeline

**`/api/documents/upload`** (the main UI path):

1. Validate the file.
2. Check for duplicates using the **SHA-256 content hash, per tenant**.
3. Write to a safe temp path.
4. Extract text. Unreadable PDFs return **422**.
5. Run the PDF agent: extract, analyze with the LLM, then store a `Contract` with `tenant_id`, `content_hash` and `original_filename`.
6. Then, in the background:
   - multi-level embeddings (`EmbeddingPipeline`);
   - chunking, keyed by the new `contract_id` and linked with `Contract-[:HAS_DOCUMENT]->Document`.
7. The temp file is always removed.

**Other paths:**

- `?enable_enhanced=true` also extracts sections, clauses and CUAD classifications through the enhanced PDF agent.
- `/api/documents/enhanced/upload` generates the embeddings before it responds.
- `/api/documents/upload-stream` sends SSE progress events: `progress`, `completion`, `error`, `end`.

**Frontend:** passes `model` as a **query parameter**.

**Dates:** `parse_date_to_iso` returns `None` for invalid dates, because Neo4j `date()` would otherwise reject the whole insert.

### 5.8 Policies

- **Upload** (PDF or TXT) goes through:
  1. validation (structure, then content);
  2. `PolicyWorkflowOrchestrator` (chunk, then extract rules with embeddings);
  3. storage in `PolicyDocument -[:HAS_RULE]-> PolicyRule` with `tenant_id` and `active=true`.
- **Soft delete** sets `active=false`. All queries filter with `coalesce(p.active, true)`.
- **Semantic search** uses `vector.similarity.cosine(r.embedding, $q)` on rules.
- **Cache** (`PolicyCacheService`):
  - uses per-tenant generation keys; invalidation bumps the generation;
  - is a pass-through unless `CACHE_ENABLED=true`.

### 5.9 Graph schema (main nodes)

**Main nodes:**

| Node | Main properties |
|---|---|
| `Contract` | `file_id` (`UPLOADED_XXXXXXXX_YYYYMMDD`), `tenant_id`, `summary`, `contract_type`, `full_text`, `effective_date`, `end_date`, `total_amount`, `embedding`, `content_hash`, `original_filename`, `intelligence_status`, `risk_*`, `last_analysis_status` |
| `Party` | `name`, `tenant_id`; linked `-[:PARTY_TO {role}]->` Contract |
| `Country` | linked `Contract -[:HAS_GOVERNING_LAW]->` Country; governing law is stored in `name` |
| `Section` | linked `Contract -[:HAS_SECTION]->` Section |
| `Clause` | linked `Section -[:CONTAINS_CLAUSE]->` Clause (section/clause extraction) **or** `Contract -[:CONTAINS_CLAUSE]->` Clause (embedding pipeline) |
| `ClauseType` | linked `Clause -[:CLASSIFIED_AS]->` ClauseType (CUAD) |
| `Document`, `Chunk` | `Contract -[:HAS_DOCUMENT]-> Document -[:HAS_CHUNK]-> Chunk`; the legacy path is `Contract -[:CONTAINS_CHUNK]-> DocumentChunk` |
| `AuditLog`, `ErrorLog` | UUID ids, `tenant_id` |
| `LegalDecision` | `tenant_id`; linked `Contract -[:HAS_DECISION]->` |
| `PerformanceMetric` | performance data |

**Clause queries:** use `(c:Contract)-[:HAS_SECTION|CONTAINS_CLAUSE*1..2]->(cl:Clause)`, because clauses hang off a contract either way.

**Known duplication:** Section and Clause nodes use either `id` or `section_id`/`clause_id` depending on which pipeline wrote them.

### 5.10 Caching and monitoring

- `cache_result(prefix, ttl, method=True)` for methods, so `self` is excluded from the key. It is a pass-through when `CACHE_ENABLED` isn't true.
- `InMemoryCache` has TTL expiry and LRU eviction (1000 entries).
- `track_performance` supports both sync and async functions.

### 5.11 MCP server (`backend/mcp_server.py`)

- **Tools:**
  - `search_clause_library(query, tenant_id)`
  - `get_playbook_rule(tenant_id, contract_type)`
  - `search_prior_approved_clauses(clause_text, tenant_id)`
  - `fetch_contract_metadata(contract_id, tenant_id)`
- **Transport:** stdio. When run, it waits silently for a client; this is normal.
- **Tenant pinning:** if `MCP_TENANT_ID` is set, any other `tenant_id` is rejected.
- **Naming rule:** the local helper package is `backend/mcp_support`. **Never add a `backend/mcp` package or module**, because it shadows the `mcp` SDK.
- The script adjusts `sys.path` itself, so no `PYTHONPATH` is needed.

---

## 6. Configuration (`.env` in the repo root, never committed)

See `.env.example` for the full list. The key variables:

| Variable | Purpose / default |
|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Neo4j. Local default `bolt://localhost:7687`; in Docker, `bolt://neo4j:7687` |
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | Gemini LLM and embeddings (needed for real use) |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (+ `ANTHROPIC_MODEL`), `MISTRAL_API_KEY` | Optional extra models |
| `ENVIRONMENT` | `development` (default) or `production` (production forces JWT auth) |
| `AUTH_MODE` | empty = automatic, `header`, or `jwt` |
| `JWT_SECRET` | Required for JWT mode |
| `DEV_DEFAULT_ROLE` | Role when there's no header in development (default ADMIN) |
| `CORS_ORIGINS` | Comma-separated. Default `http://localhost:3000,http://localhost:5173` |
| `GUARD_FAIL_CLOSED`, `GUARD_MODEL` | Guard behaviour and model |
| `MCP_TENANT_ID` | Pins the MCP server to one tenant |
| `PHOENIX_COLLECTOR_ENDPOINT`, `TRACING_ENABLED` | Tracing only when the endpoint is set |
| `CACHE_ENABLED`, `REDIS_URL` | Cache is off by default |
| `UPLOAD_TMP_DIR` | Temp directory for uploads (default `/tmp`) |
| `VITE_BACKEND_URL` | Vite dev proxy target |
| `VITE_API_BASE_URL` | Optional absolute API base for the frontend (default: same origin) |

---

## 7. How to run

### 7.1 Backend environment (once, then after dependency changes)

```powershell
cd backend
uv sync          # uses backend/uv.lock; creates backend\.venv with Python 3.12
cd ..
```

### 7.2 Tests (offline; no Neo4j or API key needed)

```powershell
backend\.venv\Scripts\python.exe -m pytest -q          # expect: 80 passed
```

- **`backend/tests/unit/conftest.py`:**
  - Patches `langchain_neo4j.Neo4jGraph` with `FakeGraph`, which records calls. Tests add `(regex, handler)` entries to `fake_graph.handlers`, and the handler returns rows.
  - Replaces Gemini embeddings with a deterministic fake.
  - Fixtures:
    - `client` (a `TestClient` for the real app)
    - `fake_llm_factory` (a canned-response chat model)
    - `use_fake_llm` (installs `StubLLMManager` as the shared manager)
- **PDFs for tests** are generated with `backend/tests/unit/pdf_fixture.py::make_pdf`. The repo's `tests/test.pdf` is **not** a real PDF.
- **Offline repro script:**
  ```powershell
  $env:PYTHONPATH="."; backend\.venv\Scripts\python.exe scripts\repro_bugs.py
  ```
  It should report `0/23`.

### 7.3 Local run (without Docker)

```powershell
# terminal 1: backend (needs Neo4j reachable per .env; starts even if not, /api/health shows degraded)
$env:PYTHONPATH="."
backend\.venv\Scripts\python.exe -m fastapi dev backend\main.py --port 8000
# terminal 2: frontend
cd frontend; npm ci; npm run dev        # http://localhost:5173 (proxies /api to :8000)
```

### 7.4 Docker

```powershell
docker compose up --build                 # neo4j + backend(:8000) + ui(:3000) + phoenix(:6006)
docker compose up --build backend ui phoenix   # when using Neo4j Aura via .env
docker compose --profile cache up --build      # also start Redis (set CACHE_ENABLED=true)
```

- **Backend image:** `uv sync --frozen --no-dev`, then `fastapi run` (no reload).
- **Frontend image:** the default target is `development` (Vite dev server). `--target production` builds an nginx image that proxies `/api` to `backend:8000`, using `frontend/nginx.conf`.

### 7.5 MCP server

```powershell
backend\.venv\Scripts\python.exe backend\mcp_server.py     # waits for a client on stdio; Ctrl+C to stop
```

For Claude Desktop, set `command` to the absolute path of `backend\.venv\Scripts\python.exe` and `args` to the absolute path of `backend\mcp_server.py`.

### 7.6 Frontend checks

```powershell
cd frontend; npm run build    # tsc -b + vite build; must pass (CI enforces it)
npx eslint .                  # 26 style errors remain (no-explicit-any etc.); not blocking
```

### 7.7 CI

`.github/workflows/ci.yml` runs on every push and pull request:

- **Backend:** `uv sync --frozen`, then pytest.
- **Frontend:** `npm ci`, then `npm run build`.

---

## 8. Rules for making changes

1. **Work on `Project1`** unless told otherwise. Commit in logical groups with clear messages, then push.
2. **Before every commit**, run:
   - `backend\.venv\Scripts\python.exe -m pytest -q` (all tests must pass);
   - `npm run build` in `frontend` when you touch frontend code.
   - Add a regression test to `backend/tests/unit/` for each bug you fix.
3. **Dependencies:** use `uv add <pkg>` (or `uv add --dev`) inside `backend/`, and commit both `pyproject.toml` and `uv.lock`. Never hand-edit the lockfile.
4. **Never:**
   - connect to Neo4j or Gemini at import time;
   - call `asyncio.run` in library code;
   - pass the LangGraph agent where a chat model is expected;
   - accept `tenant_id` from a request body, query string or the LLM;
   - add a route without `requires_permission` (the test will fail);
   - use GDS functions;
   - create a `backend/mcp` package.
5. **Keep API errors honest:**
   - add `except HTTPException: raise` before any generic `except Exception`;
   - don't turn failures into "success" or empty results;
   - use `to_json_safe()` (`backend/shared/utils/utils.py`) before returning Neo4j temporal values.
6. **Windows compatibility:** use `os.path.join` and `tempfile`, not hardcoded `/tmp`, for new code. The upload temp dir comes from `UPLOAD_TMP_DIR`.
7. **Secrets:** never commit `.env`, API keys or database passwords.

---

## 9. API changes the frontend and team should know

- **Tenant:** comes from the identity: the `X-Tenant-ID` header in development, the JWT claim in production. The `tenant_id` query and form parameters were removed from uploads, intelligence, policies, feedback and supervisor.
- **Policies:**
  - listing moved to `GET /api/policies/tenant`; the old `/tenant/{id}` returns 403 for other tenants;
  - applicable rules moved to `GET /api/policies/applicable/{contract_type}`;
  - uploads accept PDF and TXT (not DOCX; DOCX returns 415).
- **Analysis failure:** `POST /api/intelligence/contracts/{id}/analyze` returns **502** with `detail` on failure. The frontend shows the detail.
- **Duplicate upload:** returns `status: "duplicate"` with `existing_contract_id` (a content match within the same tenant).
- **Patterns:** requests accept `max_iterations` (1 to 10). The default `task_type` `"analysis"` is supported.
- **Supervisor:**
  - `workflow_id` is generated if it isn't provided;
  - status can be `completed`, `partial` or `failed`;
  - status lookups are tenant-checked (404 otherwise).
- **Search:** clause, section and relationship endpoints return the same shape as `/search/enhanced`. Database errors return 500 instead of "no results".

---

## 10. Remaining limitations (not fixed; candidates for next work)

1. **No login flow.**
   - Production requires a JWT, but no UI or endpoint issues tokens.
   - An identity provider (for example Auth0, Keycloak or Azure AD) or a simple `/api/auth/login` must be chosen.
   - The frontend needs a login page and a fetch wrapper that adds `Authorization`.
   - **This is the recommended first "new feature".**
2. **`workflow_tracker` is process-wide**, so the live agent panel shows the most recent run on the server. It should be scoped per request or tenant (for example keyed by correlation id).
3. **The planner is rule-based.** It is fed a fixed query, so it always picks the same strategy.
4. **Output guard runs after streaming.** An answer blocked for non-PII reasons is visible briefly before the `retract` event.
5. **"Llama Guard" is Gemini-based**, not a real Llama Guard model.
6. **Section and Clause id properties are inconsistent** (`id` vs `section_id`/`clause_id`).
7. **Lint and legacy tests.** 26 ESLint style errors remain. The live-service scripts in `tests/` weren't updated.
8. **ContentValidationService.** Its contract content checks flag many real contracts as having issues. This is only logged as a warning, but the rules deserve review.

### One-off migration for databases created before the fixes

Run in the Neo4j Browser:

```cypher
MATCH (c:Contract {tenant_id: 'demo_tenant_1'}) SET c.tenant_id = 'default-tenant';

MATCH (p:Party)-[r:PARTY_TO]->(c:Contract) WHERE p.tenant_id IS NULL
MERGE (tp:Party {name: p.name, tenant_id: c.tenant_id})
MERGE (tp)-[:PARTY_TO {role: r.role}]->(c)
DELETE r;
MATCH (p:Party) WHERE p.tenant_id IS NULL AND NOT (p)--() DELETE p;

MATCH (c:Contract {intelligence_status: 'completed', risk_level: 'UNKNOWN'})
SET c.intelligence_status = 'needs_reanalysis';
```

---

## 11. Suggested next steps (in order)

1. Resolve the `docker-compose.yml` pull conflict (section 2), then run `uv sync`, the tests and the app, and confirm the upload, analysis, chat and search flows end to end against a real Neo4j with `GOOGLE_API_KEY`.
2. Run the data migration (section 10) if using an existing database.
3. **Feature: authentication.** Add a login endpoint or identity provider plus frontend login, and issue JWTs with `role` and `tenant_id`. `rbac.py` already validates them.
4. Scope `workflow_tracker` per request or tenant.
5. Replace the rule-based planner input with the user's actual request or contract type.
6. Clean up the ESLint errors, unify Section and Clause ids, and update or retire the legacy `tests/` scripts.
7. Then move on to the owner's planned new features.

---

## 12. Quick reference: common tasks

| Task | Command (PowerShell) |
|---|---|
| Update code | `git pull origin Project1` |
| Install/refresh backend deps | `cd backend; uv sync; cd ..` |
| Run backend tests | `backend\.venv\Scripts\python.exe -m pytest -q` |
| Run one test file | `backend\.venv\Scripts\python.exe -m pytest -q backend\tests\unit\test_uploads.py` |
| Run backend (dev) | `$env:PYTHONPATH="."; backend\.venv\Scripts\python.exe -m fastapi dev backend\main.py` |
| Run frontend (dev) | `cd frontend; npm ci; npm run dev` |
| Build frontend | `cd frontend; npm run build` |
| Everything in Docker | `docker compose up --build` |
| MCP server | `backend\.venv\Scripts\python.exe backend\mcp_server.py` |
| Health check | `curl http://localhost:8000/api/health` |
| Issue a dev JWT | `$env:JWT_SECRET="..."; $env:PYTHONPATH="."; backend\.venv\Scripts\python.exe -c "from backend.governance.rbac import create_access_token as t; print(t('me','ADMIN','default-tenant'))"` |
