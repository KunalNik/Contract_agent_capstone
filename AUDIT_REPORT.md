# Contract Agent Capstone: Prioritized Audit Report

> **Fix status:** the findings in this report and `BUG_REPORT.md`, plus about 25 more found during the third review, are fixed on `Project1`. They were fixed in these commits:
>
> | Commit | Scope |
> |---|---|
> | `6bcb3ad` | Startup, chat and guards |
> | `70723c5` | Contract intelligence |
> | `fd7d657` | Uploads |
> | `59f0d27` | Policies, patterns, supervisor, search, MCP, feedback and audit |
> | `c328c0c` | Security configuration, frontend build and Docker |
>
> Verification:
> - `pytest -q` passes 80 offline regression tests.
> - `scripts/repro_bugs.py` reports **0/23** reproduced.
> - `npm run build` passes.
>
> See "Remaining limitations" at the end of this report.

**Branch:** `Project1` · **Builds on:** the repository inventory (Prompt 1) and `BUG_REPORT.md`

**Evidence:** `scripts/repro_bugs.py` runs the real app with Neo4j and Gemini stubbed out. On this branch it reproduces **23 of 23 checks**. Every item below gives its check ID, so you can rerun it with:

```bash
cd backend && uv sync && cd ..
PYTHONPATH=. backend/.venv/bin/python scripts/repro_bugs.py
```

**Effort scale:** S = under 4 h · M = 0.5–2 days · L = 3–5 days · XL = more than 1 week (one developer who knows the codebase)

**Priority:**
- **P0** blocks core use or is exploitable.
- **P1** is a major feature that is broken or silently wrong.
- **P2** is degraded behaviour or tech debt.

---

## 1. Executive summary

The architecture is sound: layered services, LangGraph agents, a governance chain, and an MCP server. But **most of the user-facing features don't work in practice**, and several look like they succeed while doing nothing.

- **The app can't start** without a reachable Neo4j and a Google key, because it connects to both at import time (F0).
- **Chat is broken for every prompt.** Two guard crashes each return an empty stream on their own (F1). Even once they're fixed, the LLM-based safety checks always "pass" because they fail open (F2).
- **Contract analysis returns the same canned result for every contract.** The clause extractor is hardcoded, and failed runs are saved as "completed" (F4).
- **Every major subsystem has at least one path that always fails:** uploads (F5), policies (F6), the patterns API (F7), the supervisor (F8), the dashboard (F9), MCP (F10) and the frontend build (F11).
- **Tenant isolation isn't enforced.** The chat LLM chooses the tenant and can run raw Cypher. RBAC trusts a header and defaults to ADMIN (S1–S4).

**Recommended path:** fix P0 in about 5–7 days, then P1 in about 10–14 days. The breakdown is in Section 6.

| Priority | Items | Estimated effort |
|---|---|---|
| P0 | F0, F1, F2, S1, S2, S3/S4 | ~6 days |
| P1 | F3, F4, F5, F6, F9, F11, S5, S6 | ~12 days |
| P2 | F7, F8, F10, R1–R6, L-items | ~8 days |

---

## 2. Inventory and baseline (from Prompt 1)

| Area | Entry point | State |
|---|---|---|
| Backend API | `backend/main.py` (FastAPI `app`) | Won't start without a live Neo4j and a Google key |
| Chat | `POST /api/run/` | Broken (F1) |
| Uploads | `/api/documents/upload`, `/upload-stream`, `/api/documents/enhanced/upload` | Partly broken (F5) |
| Intelligence | `/api/intelligence/contracts/{id}/analyze`, `/dashboard/summary` | Canned results (F4); dashboard returns 500 (F9) |
| Search | `/api/contracts/search/*` | Works, but ignores tenant (S1, S4) |
| Policies | `/api/policies/*` | Upload and listing return 500 (F6) |
| Patterns / Supervisor | `/api/patterns/*`, `/api/supervisor/*` | Broken (F7, F8) |
| Feedback / Monitoring / Audit | `/api/feedback/*`, `/api/monitoring/*`, `/api/audit/*` | Load fine; no auth by default (S3) |
| MCP server | `backend/mcp_server.py` | 1 of 4 tools always fails, 1 is always empty (F10) |
| Frontend | `frontend/` (`npm run dev`) | Dev server runs; `npm run build` fails with 38 TS errors (F11) |
| Training | `training/runpod/launch.sh` | Not audited: needs a GPU (RunPod) |
| Tests | `backend/tests/` (2 real unit files, 8 tests, all pass); `tests/` (16 scripts needing live services) | None cover the broken paths |

---

## 3. Broken or incomplete features

### F0 · App can't start without live Neo4j and Google key · **P0 · M (1 day)**
**Repro:**
1. Unset `GOOGLE_API_KEY` and run `PYTHONPATH=. backend/.venv/bin/uvicorn backend.main:app`.
2. Separately, set `NEO4J_URI=bolt://127.0.0.1:7687` with no database running, and start it again.

**Evidence:**
- Step 1: `ValueError: GOOGLE_API_KEY or GEMINI_API_KEY required`
- Step 2: `ValueError: Could not connect to Neo4j database`
- With the `.env.example` placeholders copied as-is: `ConfigurationError: URI scheme '' is not supported`

**Root cause:** module-level singletons. The import chain is `main.py:11` → `llm_manager.py:10` → `contract_chat_agent.py:1` → `contract_search_tool.py:53` (`graph = Neo4jGraph(...)`) plus `gemini_embedding_service.py:77` (`embedding = GeminiEmbeddingService()`). `docker-compose.yml` has no Neo4j service and falls back to the read-only demo database.

**Plan:**
1. Replace the module globals with lazy `get_graph()` / `get_embedding()` providers (cached with `functools.lru_cache`). Update the roughly 15 import sites.
2. Build them in the FastAPI `lifespan` and log a clear error there.
3. Add `neo4j:5` and `redis` services to `docker-compose.yml`, and change `.env.example` to `NEO4J_URI=bolt://neo4j:7687`.
4. Add `GET /health` that reports database and LLM readiness.

---

### F1 · Chat (`/api/run/`) returns an empty stream for every prompt · **P0 · S (2 h)**
**Repro:** `curl -N -X POST :8000/api/run/ -H 'Content-Type: application/json' -d '{"model":"gemini-2.5-flash","prompt":"What are the termination clauses?","history":"[]"}'`

**Evidence:** checks F1 ×3: `HTTP 200, body bytes=0`; `NameError: name 'prompt' is not defined`; `NameError: name 'e' is not defined`.

**Root cause:**
1. `governance/validators/injection.py:21` uses `prompt` where it means `input_text`. This validator is first in the chain, so it runs on every prompt.
2. `validators/intent.py:51-53` has `except Exception:` but then logs `e`. Because of F2 the `try` always fails, so this fires on every prompt of 5 or more words.
3. `main.py:289` uses `AuditEventType` without importing it, which crashes whenever PII redaction applies.

All three exceptions are raised inside the SSE generator, so the client just sees the stream close.

**Plan:**
1. Fix the variable name in `injection.py` and add `as e` in `intent.py`.
2. Import `AuditEventType` in `main.py`.
3. Wrap the `runner()` body in `try/except`, and on failure emit `{"type":"error"}` followed by `{"type":"end"}`.
4. Add a `TestClient` test that asserts the stream ends with an `end` event.

---

### F2 · LLM-based guards always pass (fail open) · **P0 · M (1 day)**
**Repro:** check F2, or call `LLMManager().get_model_by_name("gemini-2.5-flash").invoke("text")`.

**Evidence:** `InvalidUpdateError: Expected dict, got System: classify ...`.

**Root cause:** `get_model_by_name()` returns the compiled LangGraph chat agent, not a chat model. The Llama-Guard, intent and hallucination checks call `.invoke(str)` on it (`safety.py:45`, `intent.py:37`, `hallucination.py:60`). They catch the error and return `is_safe=True`. Each validator also builds its own `LLMManager()` on every request, which rebuilds every agent graph.

**Plan:**
1. Add `LLMManager.get_chat_model(name)` that returns the raw `ChatGoogleGenerativeAI` (store it next to the agent in `init_agents`).
2. Inject a shared `LLMManager` into the guards; don't construct one per validator.
3. Use `with_structured_output(PydanticModel)` instead of parsing JSON out of the text reply.
4. Decide the policy explicitly: output guards should **fail closed** (block or flag on error) and emit an audit event.
5. Run guard calls with `await model.ainvoke`.
6. Note that `LlamaGuardValidator` is Gemini *imitating* Llama Guard. Either rename it or call a real Llama Guard endpoint.

---

### F3 · Topic and keyword guards block normal questions · **P1 · S (3 h)**
**Evidence:** checks F3 ×2: "What are the payment terms?" → `OUT_OF_SCOPE`; "list the administrative fees clause" → `SENSITIVE_CONTENT`.

**Root cause:**
- `topic.py:35` rejects any prompt of 4 or more words that lacks one of about 18 whitelisted words ("payment", "NDA", "renewal" and "fee" are all missing).
- `keyword.py:8` does substring matching on "admin" and "root".

**Plan:**
1. Make the topic check advisory: return a warning, not a block, and let the (fixed) intent classifier make the call.
2. Grow the vocabulary from `CONTRACT_TYPES` and the CUAD clause names.
3. Switch the keyword check to word-boundary regexes (`\badmin\b`, `\bpassword\b`).
4. Add a table-driven test with about 30 real user questions that must pass.

---

### F4 · Contract intelligence returns canned, inconsistent or silently failed results · **P1 · L (4–5 days)**
**Repro:**
1. Upload any two different contracts.
2. `POST /api/intelligence/contracts/{id}/analyze` for each one.
3. Also try `?use_planning=false` on a contract longer than 10k characters.

**Evidence:**
- Two different contracts give identical clause output.
- A "Shipping" clause is flagged as an IP violation.
- The non-planning path returns `clauses=0 risk=UNKNOWN`.

**Root cause:**
1. `intelligence_tools.py:91-134`: `ClauseDetectorTool` builds a prompt but returns two hardcoded clauses. So every contract gets the same result: 1 HIGH violation ("$50,000 liability"), 1 CRITICAL redline, risk 45.
2. `IntelligenceOrchestrator` never uses `self.llm`. `contract_intelligence_service.py:367` would hand it the agent graph anyway (F2), so the `model=` parameter does nothing.
3. `contract_intelligence_agents.py:96,110`: `asyncio.run()` inside a running event loop raises `RuntimeError`. Nothing catches it, so the result comes back empty.
4. `contract_intelligence_service.py:315-356` saves those empty or failed results with `intelligence_status='completed'`.
5. The planner is fed a hardcoded query (`:422`), so it always picks the same strategy. Its path has no pattern step and doesn't merge CUAD deviations, so it gives different results from the traditional path.
6. `"ip" in clause_type` also matches "Shipping", "Relationship" and "Membership" (`:223`, `:360`).
7. `IntelligenceState` has no `validation_result` key, so the validation score is dropped.

**Plan:**
1. **(L)** Make `ClauseDetectorTool` take an injected chat model. Call `llm.with_structured_output(list[ClauseModel])` over chunked text (reuse `ChunkingAgent`'s sections) and merge the results. Keep the current stub only behind `USE_STUB_EXTRACTION=true`, for tests.
2. **(S)** Pass the real model from `LLMManager.get_chat_model(model)` through the factory into the tools.
3. **(M)** Make the orchestrator async end to end: `async def analyze_contract` → `await self.workflow.ainvoke(...)`, async graph nodes that `await agent.execute(...)`, and delete the thread-pool workaround.
4. **(S)** On failure, save `intelligence_status='failed'` with the error, and return 502 to the caller.
5. **(M)** Build one pipeline: have the planner choose *which* steps to run, but share node implementations with the LangGraph workflow so both paths merge deviations the same way. Pass the user's query (or contract type) into the planner.
6. **(S)** Use word-boundary or enum matching for clause types. Add `validation_result` to `IntelligenceState`.
7. **(M)** Add golden tests: 3 fixture contracts with expected clause types and violations.

---

### F5 · Upload paths fail or lose data · **P1 · M (1.5 days)**

**F5a · Duplicate detection crashes**
- **Repro:** upload `nda.pdf` twice.
- **Evidence:** `HTTP 500 {"detail":"Processing failed: 'file_id'"}`
- **Root cause:** the query aliases the column as `c.file_id` but the code reads `["file_id"]` (`document_upload.py:167/180`, `enhanced_document_upload.py:149/161`). The match is also a `CONTAINS` substring test across all tenants.

**F5b · Enhanced upload always fails**
- **Repro:** `POST /api/documents/enhanced/upload` (default `enable_embeddings=true`).
- **Evidence:** `TypeError: No synchronous function provided to "store_contract"`.
- **Root cause:** `enhanced_document_processing_service.py:109` calls sync `.invoke()` on a graph whose `store_contract` node is `async`. The same service's `initial_state` (line 97) also has no `tenant_id`.

**F5c · The `enable_embeddings=false` branch never works**
- **Root cause:** it calls `process_pdf_upload` without `await` (`enhanced_document_upload.py:219`).

**F5d · Basic upload never creates multi-level embeddings**
- **Evidence:** the method it calls doesn't exist on that class.
- **Root cause:** `document_processing_service.py:136`. The error is only logged as a warning.

**F5e · `?enable_enhanced=true` always fails**
- **Root cause:** `document_upload.py:314` passes the agent graph as the LLM (same cause as F2).

**Plan:**
1. Alias the column as `file_id` and check duplicates by a SHA-256 content hash scoped to `tenant_id`.
2. Make the enhanced service `async`, use `await pdf_agent.ainvoke(...)`, and add `tenant_id` to the state.
3. `await` the fallback call.
4. Move `_process_enhanced_embeddings` into a shared `EmbeddingPipeline` that both services call.
5. Use `get_chat_model()` for the processors.
6. Clean up the temp file in a `finally` block on every path.
7. Add a TestClient test for each upload route.

---

### F6 · Policy management is non-functional · **P1 · M (2 days)**
**Repro:**
```bash
curl -F file=@policy.txt -F tenant_id=t1 -F policy_name=p :8000/api/policies/upload
curl :8000/api/policies/tenant/t1
curl :8000/api/policies/nope
```
**Evidence:**
- Upload: 500 `SupervisorAgent.__init__() missing 2 required positional arguments`
- Tenant listing: 500 `name 'AuditEvent' is not defined`
- Unknown ID: 500 `404: Policy not found`

**Root cause:**
1. `policy_workflow_orchestrator.py:14` constructs `SupervisorAgent()` with no arguments, even though the supervisor isn't used.
2. `policy_audit_service.py:56,77,97,117,...` uses an `AuditEvent` class that doesn't exist.
3. `policy_agents.py:35,71` calls `asyncio.run` inside the event loop, and `import asyncio` is missing.
4. `policy_api.py:43` decodes every file as UTF-8, so the advertised PDF and DOCX uploads can't work.
5. `policy_service.py:28,75` calls `track_error` with the wrong signature.
6. Every route wraps `HTTPException` in `except Exception`, so 400/404 become 500.
7. Semantic search needs `PolicyDocument.embedding` (never written) and GDS `gds.similarity.cosine` (not available on Aura Free).

**Plan:**
1. Remove the unused supervisor from the orchestrator and make the agents `async`, awaiting storage directly.
2. Rewrite the `log_policy_*` methods to call `AuditLogger.log_event(...)`, following the upload and processing methods.
3. Extract text through `TextExtractionService` for PDFs, plus `python-docx` for DOCX.
4. Fix the `track_error` calls, and add `except HTTPException: raise` before the generic handler.
5. On upload, embed each rule and store it on `PolicyRule.embedding`. Create a vector index and query it with `db.index.vector.queryNodes` instead of GDS.
6. Add a test covering upload → list → search → compliance check.

---

### F7 · Patterns API broken · **P2 · S (3 h)**
**Evidence:** `/api/patterns/react` and `/chain-of-thought` return 500 with `'ReACTAgent' object has no attribute 'process'`. `/analyze` always returns `success:false`.

**Root cause:**
- The agents expose `execute()`, but `patterns_api.py:84,107` and `pattern_orchestrator.py:81,99` call `process()`.
- `/react` passes `request.patterns[0]` (the string `"react"`) as `max_iterations`.
- CoT uses an undefined `overall_risk` variable (`chain_of_thought_agent.py:120`) and reads `clause['type']` where the data has `clause_type`.
- ReACT never calls an LLM, and its confidence never converges, so it always runs the maximum number of iterations.

**Plan:**
1. Call `.execute()`. Add a `max_iterations: int = 3` field to the request.
2. Define `overall_risk` as the maximum of the severity scores, and use `clause_type`.
3. Reset `thought_chain` on each call.
4. (Optional, M) Give ReACT a real LLM reason→tool→observe loop using `create_react_agent` from langgraph.

---

### F8 · Supervisor workflow does no real work · **P2 · M (1 day)**
**Evidence:** `/api/supervisor/workflow/{id}/status` always returns "Workflow not found". `execute` reports "completed" even when every step failed.

**Root cause:**
- Steps never receive `input_data` (`supervisor_agent.py:272`).
- The adapters return coroutines without awaiting them (`adapters.py:31,119,164`).
- The adapters look up `"pdf-processing"`, but the agent is registered as `pdf_processing`.
- The model name is passed as `tenant_id`.
- A new supervisor is created on every request, so state is lost.
- `BaseAgentAdapter` swallows exceptions, so retry and circuit breaking never trigger.

**Plan:**
1. Make the adapters and `coordinate_workflow` async.
2. Pass `request.input_data` into the first step, and fix the IDs and argument order.
3. Keep a module-level supervisor with a bounded store of workflow states.
4. Re-raise errors in the adapters so the retry and circuit-breaker logic can act.
5. Set the overall status from the step results.

---

### F9 · Intelligence dashboard returns 500 until a contract is analysed · **P1 · S (1 h)**
**Evidence:** `HTTP 500 ... NoneType doesn't define __round__`.

**Root cause:** `contract_intelligence.py:226` calls `round()` on `avg()`, which is `null` when there are no rows. It also hardcodes `"default-tenant"` (lines 132 and 220), and the status route has no auth.

**Plan:** use `round(stats.get("avg_risk_score") or 0.0, 2)` and `or 0` for the sums; accept `tenant_id` from the auth context; add `requires_permission`.

---

### F10 · MCP tools broken or always empty · **P2 · S (3 h)**
**Evidence:** check F10: `fetch_contract_metadata` returns `Object of type coroutine is not JSON serializable`.

**Root cause:**
- `mcp_server.py:122` doesn't `await` the async `get_contract_by_id`.
- `search_clause_library` depends on policy embeddings that are never written (F6).
- MCP has no authentication: the caller supplies `tenant_id`.

**Plan:**
1. Add the missing `await`.
2. Fix after F6's embedding work lands.
3. Add a shared-secret or OAuth check in `mcp_tool_wrapper`, and map the credential to a tenant server-side.
4. Add a test for all 4 tools with the stubbed graph.

---

### F11 · Frontend production build fails, and some API URLs are wrong · **P1 · M (1 day)**
**Repro:** `cd frontend && npm ci && npm run build`

**Evidence:** 38 TypeScript errors.

**Root cause:**
- `enhancedSearchApi.ts:1` imports a path that doesn't exist.
- `ContractIntelligence.tsx:104,362` has argument-count and prop mismatches.
- There are `SearchPage.tsx:40` and `message.tsx:31` type errors, about 20 unused imports, and some implicit-`any` index types.
- `enhancedSearchApi.ts:72,89` call `/documents/enhanced/...` without the `/api` prefix, so they 404.
- The API base URL is hardcoded to `http://localhost:8000`.
- The frontend Docker image only runs the dev server, so a broken build is never noticed.

**Plan:**
1. Fix the import and the two call-site signatures.
2. Type the lookup maps with `Record<string, ...>` and remove the unused imports.
3. Use relative `/api/...` URLs so requests go through the Vite proxy.
4. Add a production stage to the Dockerfile (`npm run build` served by nginx).
5. Add `npm run build` to CI.

---

## 4. Security findings

### S1 · The LLM chooses the tenant in chat search · **P0 · M (1 day)**
**Evidence:** check S1: the LLM-fillable tool arguments include `tenant_id`.

**Repro:** ask the chat "search contracts for tenant acme-corp". The model passes `tenant_id="acme-corp"`.

**Root cause:** `ContractInput.tenant_id` (`contract_search_tool.py:218`, and the same in `enhanced_contract_search_tool.py:392`) is part of the tool schema. There's also a functional side effect: the model has to guess the tenant, so contracts uploaded under `default-tenant` are often never found.

**Plan:**
1. Remove `tenant_id` from the tool schemas.
2. Build the tools per request, with the tenant bound in via `functools.partial` or the tool's constructor, taken from the authenticated request context (depends on S3).
3. Pass it through `get_agent(llm, tenant_id)`.
4. Add a test that asserts the tool JSON schema has no `tenant_id`.

### S2 · LLM-authored Cypher runs against the database · **P0 · S (3 h)**
**Evidence:** check S1: the schema also includes `cypher_aggregation`.

**Repro:** a prompt such as "use cypher_aggregation `WITH 1 AS x MATCH (n) DETACH DELETE n RETURN 0`". The prompt guards that should screen this are broken (F1, F2).

**Root cause:** `contract_search_tool.py:168-169` appends the string straight onto the query.

**Plan:**
1. Remove `cypher_aggregation`, or replace it with an enum of pre-written aggregation queries (count by type, by party, by year).
2. Run tool queries on a read-only Neo4j user or session (`default_access_mode=READ`).

### S3 / S4 · RBAC defaults to ADMIN and trusts client headers; tenant is a free parameter · **P0 · L (3 days)**
**Evidence:**
- Check S3: a request with no role header gets 200 on `/api/audit/errors/recent`.
- The frontend never sends `X-User-Role` or `tenant_id`, so all data lands in `default-tenant`.

**Root cause:**
- `rbac.py:59` returns `UserRole.ADMIN` when the header is missing, and otherwise trusts `X-User-Role` from the client.
- `tenant_id` is a query parameter on every route.
- `run()` never passes `user_role` to `runner()`.

**Plan:**
1. Add JWT authentication (for example FastAPI with `python-jose`, or an OIDC provider). Claims: `sub`, `role`, `tenant_id`.
2. `get_current_user()` validates the token and returns `User(role, tenant_id)`. Change the missing-token default to **401**.
3. Remove the `tenant_id` query and form parameters; read the tenant from `user.tenant_id`.
4. On the frontend, add a login page and a `fetch` wrapper that adds `Authorization`. Until auth ships, a dev-mode flag can inject a fixed token.
5. **Order matters:** changing the ADMIN default alone will lock the current UI out.

### S5 · Unauthenticated and debug endpoints are exposed · **P1 · S (2 h)**
**Evidence:** check S5: `/api/documents/debug/contracts` returns 200 and lists contracts across tenants.

**Root cause:** `document_upload.py:28-85` mounts the debug routes regardless of `ENVIRONMENT`. These routes have no auth or tenant check:
- `/api/intelligence/contracts/{id}/status`
- `/api/documents/enhanced/embedding-status/{id}`
- `/api/policies/applicable/...`
- `/api/supervisor/workflow/{id}/status`

**Plan:** delete the duplicate debug routes (the `routes/debug.py` copies are already gated on environment); add `requires_permission` and a tenant filter to the others; add a test that walks `app.routes` and fails if any `/api/*` route lacks an auth dependency.

### S6 · Graph data is shared across tenants (IDOR) · **P1 · M (1 day)**
**Root cause:**
- `contract_repository.py:156,175` MERGEs `Party` and `Country` nodes globally by name.
- `Section` and `Clause` IDs don't include the tenant.
- Policy `GET` and `DELETE /{policy_id}` don't check the tenant.

**Plan:**
1. Add `tenant_id` to the MERGE keys for party, section and clause nodes.
2. Write a migration that splits the existing shared nodes.
3. Add `tenant_id` to every by-ID query.
4. Add a composite uniqueness constraint on `(tenant_id, id)`.

### S7 · PII leaks through streaming and audit logs · **P1 · M (1 day)**
**Root cause:**
- The output guard and PII redaction run *after* tokens have already been streamed (`main.py:217-268`).
- On a guard violation, `base.py:92-97` copies `context_metadata`, including the whole contract (`source_text`), into the audit log.

**Plan:**
1. Redact each chunk as it streams, keeping a small overlap window so patterns split across chunks are still caught. Alternatively, buffer and stream only after the guards pass when a "strict" mode is on.
2. Remove `source_text` from the audit metadata.

### S8 · CORS allows any origin with credentials · **P2 · S (30 min)**
**Root cause:** `main.py:63-69`.

**Plan:** read the allowed origins from an env var such as `CORS_ORIGINS`.

---

## 5. Reliability, performance, quality and test gaps

| ID | Issue | Location | Fix | Effort |
|---|---|---|---|---|
| R1 | Analysis, guards and supervisor block the event loop, so the whole server stalls during an analysis | `contract_intelligence_agents.py:386`, sync `invoke` calls, `retry_manager.time.sleep` | Go async end to end (F4 step 3). Use `asyncio.to_thread` for the sync Neo4j driver calls, or switch to `AsyncGraphDatabase` | M |
| R2 | `workflow_tracker` is global state shared across requests and threads | `agent_workflow_tracker.py` | Scope it per request (a context variable keyed by correlation ID) | M |
| R3 | In-memory cache has no TTL or size limit; `CACHE_ENABLED` is ignored; `@track_performance` times async functions as about 0 ms | `redis_cache.py`, `performance_monitor.py:96` | Use `cachetools.TTLCache`, honour the flag, add an async-aware decorator | S |
| R4 | Retired models (`claude-3-5-sonnet-latest`, `gemini-1.5-pro`); `/models` offers models the upload services reject; `LLMManager.agents` is a class-level dict | `llm_manager.py`, `*_processing_service._get_llm_for_model` | Keep one model registry in `LLMManager` and use it everywhere | S |
| R5 | Docker runs `fastapi dev`; Compose has no Neo4j or Redis | `backend/Dockerfile`, `docker-compose.yml` | `fastapi run`, add the services (see F0) | S |
| R6 | The default tenant has three different names (`default-tenant`, `demo_tenant_1`, `default`); duplicate `tenant_id` key in a Cypher map | various; `contract_repository.py:87,96` | One constant, `DEFAULT_TENANT`, until S3/S4 removes the need | S |
| L1 | Every upload is audited twice; the `audit_log` decorator has a precedence bug | `document_upload.py:88`, `audit_logger.py:44` | Keep one audit call; add parentheses | S |
| L2 | Dead or broken modules: `backend/dependencies.py`, `api/contracts.py` (never mounted), `supervisor/factory.py`, `agents/policy_workflow_supervisor.py` | — | Delete them, or fix and mount them | S |

**Test gaps:**
- Only 8 unit tests run offline. The 16 scripts in `tests/` need live services and aren't collected by pytest.
- There's no CI.

**Recommended:**
1. Add `backend/tests/conftest.py` with a `FakeGraph` fixture and an LLM fixture built on `FakeMessagesListChatModel`.
2. Turn the checks in `scripts/repro_bugs.py` into pytest cases (the goal: all 23 pass once fixed).
3. Add route tests for each router.
4. Add a GitHub Actions workflow running `uv sync`, `pytest`, `pyflakes`, and `npm ci && npm run build && npm run lint`.
5. Mark the live-service scripts with `@pytest.mark.integration`.

**Effort:** M (2 days).

---

## 6. Prioritized remediation roadmap

| Phase | Goal | Items | Effort | Done when |
|---|---|---|---|---|
| **0: Safety net** (day 1) | Make bugs visible | Test fixtures, repro checks as pytest, CI | 1 d | CI runs and shows 23 expected failures |
| **1: Unblock** (days 2–3) | App starts; chat works | F0, F1, F9, F5a | 2 d | App starts without a DB; chat stream ends with `end`; dashboard 200; duplicate upload 200 |
| **2: Close exploits** (days 4–7) | No cross-tenant or DB-write paths | S2, S1, S5, S3/S4 (auth, tenant from token), S8 | 4 d | S1/S3/S5 checks pass; tool schema has no `tenant_id` or `cypher_aggregation`; routes without auth return 401 |
| **3: Real guards** (day 8) | Guards actually evaluate | F2, F3, S7 | 2 d | Guard checks pass; about 30 real questions allowed; injection samples blocked |
| **4: Real analysis** (days 9–14) | Results reflect the contract | F4 (LLM extraction, async, failure status, single pipeline), R1, R2 | 5–6 d | Golden-contract tests pass; two different contracts give different results; server responsive during analysis |
| **5: Complete subsystems** (days 15–19) | Remaining features work | F5b–e, F6, F11, S6 | 5 d | Upload, policy and frontend-build checks pass; tenant-scoped graph migration applied |
| **6: Polish** (days 20–22) | Secondary features and debt | F7, F8, F10, R3–R6, L1–L2 | 3 d | All 23 repro checks pass; `pyflakes` clean |

**Total:** about 22–24 developer-days, or roughly 2 weeks for two developers working in parallel (Phase 2 and Phase 3 can overlap, as can Phase 4 and Phase 5).

**Dependencies:**
- S3/S4 (auth) must land before S1 (tenant binding) can use a trusted tenant.
- F2 (`get_chat_model`) comes before F4 and F5e.
- F6's embedding work comes before F10's `search_clause_library`.


---

## Remaining limitations (not fixed)

These are design decisions or follow-up work, not quick fixes.

1. **No login flow.** Production now requires a signed JWT (`AUTH_MODE=jwt`, claims `sub`, `role`, `tenant_id`), but nothing issues tokens yet. `governance.rbac.create_access_token` exists for scripts and tests. Choosing an identity provider is a team decision.
2. **The workflow tracker is process-wide.** The live agent-workflow panel shows the most recent run on the server, not per user or tenant.
3. **The planner is still rule-based.** It is fed a fixed query, so it always picks the same strategy. Both analysis paths now give consistent results.
4. **The output guard runs after streaming.** PII is redacted while streaming. An answer blocked for other reasons is shown briefly and then retracted by a `retract` event.
5. **"Llama Guard" is Gemini.** It is prompted with the Llama Guard taxonomy and does not call a Llama Guard model.
6. **Some schema duplication remains.** `Section`/`Clause` nodes use either `id` or `section_id`/`clause_id` depending on which pipeline wrote them. Queries now match both relationship paths.
7. **Lint and legacy tests.** 26 ESLint style errors remain (`no-explicit-any` and similar); the build passes. The live-service scripts under `tests/` were not updated.

### One-off data migration for existing databases

Run this once on databases created before these fixes:

```cypher
// Contracts assigned to the old demo tenant by the enterprise migration
MATCH (c:Contract {tenant_id: 'demo_tenant_1'}) SET c.tenant_id = 'default-tenant';

// Party nodes used to be shared across tenants: split them per tenant
MATCH (p:Party)-[r:PARTY_TO]->(c:Contract)
WHERE p.tenant_id IS NULL
MERGE (tp:Party {name: p.name, tenant_id: c.tenant_id})
MERGE (tp)-[:PARTY_TO {role: r.role}]->(c)
DELETE r;
MATCH (p:Party) WHERE p.tenant_id IS NULL AND NOT (p)--() DELETE p;

// Stale aggregate markers from failed runs stored as "completed" cannot be
// told apart automatically; re-run analysis for contracts with risk_level 'UNKNOWN'
MATCH (c:Contract {intelligence_status: 'completed', risk_level: 'UNKNOWN'})
SET c.intelligence_status = 'needs_reanalysis';
```
