# Contract Agent Capstone: Bug Audit (second pass)

> **Status:** fixed on `Project1`. See the fix-status note and remaining limitations in `AUDIT_REPORT.md`.

Branch audited: `Project1` @ `7b7ac9a`

## How this pass was verified

The first pass was mostly done by reading the code. This pass also ran it:

- Installed the backend with `uv sync` and **imported every backend module**, with a stub standing in for the Neo4j driver.
- Ran `pyflakes` across `backend/`, `tests/`, `scripts/` and `training/` to find undefined names.
- **Drove the real FastAPI app** with `TestClient` against a stubbed graph and recorded the HTTP responses (marked **[verified]** below).
- Called the guard validators directly, and checked the LangGraph behaviour with minimal reproductions.
- Ran `tsc -b` and `eslint` on the frontend.

---

## Part 1: Corrections to the first report

| # | Earlier claim | What is actually true |
|---|---|---|
| C1 | `contracts.py` crashes because `process_pdf_upload` is not awaited | The bug is real, but `backend/api/contracts.py`'s router is **never mounted** in `main.py`. It's dead code that no user can reach. |
| C2 | `/upload/pdf/enhanced` crashes with an "event loop nesting" error | The route is `/api/documents/enhanced/upload`. The failure is LangGraph's `TypeError: No synchronous function provided to "store_contract"`: the code calls sync `.invoke()` on a graph that has an `async` node. The result is the same (it always fails), and the failure comes **after** the LLM analysis has already been paid for. |
| C3 | Supervisor adapters call `get_agent_result()`, which doesn't exist | That method **does exist** (`supervisor/workflow_context.py:25`). The real bugs are listed under N17: an ID mismatch, un-awaited coroutines, and missing inputs. |
| C4 | The CoT `overall_risk` NameError crashes the risk flow | `BasePatternAgent.execute` catches it, so it silently returns `{'success': False}`. It is still broken, but it doesn't crash anything. |
| C5 | ReACT/CoT never run because violations are checked before they're computed | The selector also looks at text length (over 10k characters selects CoT). The real reasons they never run: (a) the **default** path (`use_planning=True`) has no pattern step at all, and (b) the non-planning path crashes on `asyncio.run` (see N6). |
| C6 | The `InjectionValidator` NameError "disables the security layer" | It's worse than that: the exception is raised inside the SSE generator, so **`/api/run/` (chat) returns an empty 200 stream for every prompt**. [verified] |

---

## Part 2: New findings

### 🔴 Critical: core features broken

**N1. Every LLM-based guard calls `.invoke(str)` on a LangGraph agent, so every check fails open**
`governance/validators/safety.py:44-45`, `intent.py:36-37`, `hallucination.py:59-60`
`LLMManager.get_model_by_name()` returns the compiled chat agent (`contract_chat_agent.get_agent`), not a chat model. Calling `graph.invoke("System: ...")` raises `InvalidUpdateError: Expected dict` [verified]. `LlamaGuardValidator` and `HallucinationValidator` catch that error and return `is_safe=True`, so the Llama-Guard and hallucination checks **never actually run**. On top of that, each validator builds a brand-new `LLMManager()` (all agent graphs) on every request.

**N2. `IntentValidator` crashes on every prompt of 5 or more words**
`governance/validators/intent.py:51-53`
The handler is `except Exception:` with no `as e`, and then it logs `{e}`, which raises a `NameError`. Because of N1 the `try` always fails, so this `NameError` fires every time. **So fixing `injection.py` alone still leaves chat broken.** [verified]

**N3. PII redaction kills the chat stream**
`main.py:289`
`AuditEventType` is never imported into `main.py`. Whenever redaction changes the output, a `NameError` is raised after the content has streamed, so the client never gets the `history` or `end` events.

**N4. Topic and keyword guards block ordinary questions**
`validators/topic.py:35`, `validators/keyword.py:8`
Any prompt of 4 or more words without a whitelisted keyword is rejected. Verified examples: "What are the payment terms?" and "Show me all NDAs with Acme" both return `OUT_OF_SCOPE`. The keyword check uses substrings, so "admin" and "root" also block "administrative fees" and "root cause". [verified]

**N5. The chosen model is ignored or broken everywhere in analysis**
- `contract_intelligence_service.py:367` hands the compiled chat graph to the orchestrator as "the LLM". `IntelligenceOrchestrator` never uses `self.llm` anyway, so the `model=` parameter has **no effect**.
- `document_upload.py:314` (`/api/documents/upload?enable_enhanced=true`) passes the graph to `LLMContractAnalyzer`, `LLMSectionExtractor`, `LLMClauseExtractor` and `LLMCUADClassifier`. Each of them calls `llm.invoke(prompt)`, so **enhanced upload always fails**.

**N6. The non-planning analysis path returns empty results for any contract over 10k characters**
`agents/contract_intelligence_agents.py:96,110`
`_pattern_analysis` calls `asyncio.run()` while it is already running on FastAPI's event loop, which raises `RuntimeError`. Nothing inside the graph catches it, so `analyze_contract()` returns an empty result with risk `"UNKNOWN"`. This affects `use_planning=false`, and also the fallback taken whenever planning fails.

**N7. Failed analyses are saved as "completed"**
`contract_intelligence_service.py:310-326` → `:356`
When analysis fails, the service returns a placeholder (`risk 0`, `UNKNOWN`), and `_store_intelligence_results` then writes `intelligence_status='completed'`. That's silent data corruption: the dashboard counts these as real results.

**N8. The "self-reflective" planner is deterministic, and its path disagrees with the traditional path**
`contract_intelligence_agents.py:422`, `planning/planning_agent.py`, `planning/execution_engine.py`
- The query is a hardcoded constant, so the planner always picks `COMPLIANCE_FOCUSED`, which runs the complex plan every time.
- The planned path has **no pattern step**, and it never merges CUAD deviations into violations (the traditional path does).
- As a result, the same contract gets different violations depending on the `use_planning` flag.
- The "parallel" steps actually run sequentially.
- `asyncio.wait_for` can't time out the sync tools, and retries never happen because the tools swallow every exception.
- `_wait_for_dependencies` spins forever if a step depends on a later step.

**N9. The Patterns API is broken** [verified]
`api/patterns_api.py:77,84,107`, `agents/patterns/pattern_orchestrator.py:81,99`

| Endpoint | Result | Cause |
|---|---|---|
| `/api/patterns/react` | 500 | `ReACTAgent` has no `.process()` method (only `.execute()`) |
| `/api/patterns/chain-of-thought` | 500 | `ChainOfThoughtAgent` has no `.process()` method (only `.execute()`) |
| `/api/patterns/analyze` | always `success:false` | the orchestrator calls the same missing `.process()` |

`/react` also passes `request.patterns[0]` (the string `"react"`) as `max_iterations`.

**N10. Policy upload always returns 500** [verified]
`agents/policy_workflow_orchestrator.py:14` calls `SupervisorAgent()` with no arguments, but it requires `registry` and `quality_manager`, so `PolicyService()` fails in its constructor. Fixing that exposes three more problems:
- `asyncio.run()` inside a running event loop (`policy_agents.py:35`)
- a missing `import asyncio` (`policy_agents.py:71`)
- `content.decode('utf-8')` (`policy_api.py:43`), so the advertised PDF and DOCX uploads can never work

**N11. `PolicyAuditService` uses an undefined `AuditEvent` class**
`infrastructure/policy_audit_service.py:56,77,97,117,...`
`GET /api/policies/tenant/{id}` returns 500 [verified]. `agents/policy_workflow_supervisor.py` imports `AuditEvent`, so that module fails to import entirely.

**N12. `PolicyService`'s error handler raises a new error**
`policy_service.py:28-32,75-79`
It calls `ErrorTracker.track_error(error_type=..., error_message=..., context=...)`, but the real signature is `(error, category, severity, context)`. The resulting `TypeError` hides the original error.

**N13. Duplicate detection crashes both upload endpoints** [verified]
`document_upload.py:167/180`, `enhanced_document_upload.py:149/161`
- The Cypher query returns the column `c.file_id`, but the code reads `["file_id"]`, so a `KeyError` produces a 500.
- The match is a `CONTAINS` substring test that ignores tenant, so `"a.pdf"` matches other tenants' contracts.

**N14. Basic upload never builds multi-level embeddings**
`document_processing_service.py:136`
It calls `self._process_enhanced_embeddings`, which only exists on the *enhanced* service. The resulting `AttributeError` is logged as a warning and ignored.

**N15. Enhanced upload drops `tenant_id`**
`enhanced_document_processing_service.py:97`
The `initial_state` has no `tenant_id`, so every contract is stored under `default-tenant`.

**N16. The intelligence dashboard returns 500 when no contracts have been analysed** [verified]
`api/contract_intelligence.py:226`
`round(None)` fails because Cypher's `avg()` returns `null` when there are no rows. The status and dashboard queries also hardcode `"default-tenant"` (lines 132 and 220).

**N17. The Supervisor workflow never does real work**
`supervisor/supervisor_agent.py:272`, `supervisor/adapters.py:31,62,107,119,164`
- Steps never receive `input_data` (`step.get("input_data")` is never set), so `file_path` is `None`.
- `process_pdf_upload` and `analyze_contract_by_id` are async but never awaited, so `format_output` gets a coroutine.
- The adapters look up `"pdf-processing"` (with a hyphen), but the agents are registered as `pdf_processing`.
- `analyze_contract_by_id(contract_id, "gemini-2.5-flash")` passes the model name as `tenant_id`.
- The workflow status is always `"completed"`, even when every step failed.
- `/workflow/{id}/status` builds a new supervisor on each request, so it always reports "Workflow not found" [verified].
- The circuit breaker and retry never trigger, because `BaseAgentAdapter.execute` catches every exception.

**N18. MCP tools are broken**
`mcp_server.py:122`
- `fetch_contract_metadata` doesn't await the async `get_contract_by_id`, so `json.dumps(coroutine)` fails **every time**.
- `search_clause_library` needs `PolicyDocument.embedding`, which nothing ever writes, and it calls the GDS function `gds.similarity.cosine`, which isn't available on Aura Free.
- MCP has no authentication. `tenant_id` is whatever the caller passes in.

**N19. The frontend production build fails**
`npm run build` stops with **38 TypeScript errors**. The real ones:
- a missing module, `enhancedSearchApi.ts:1` (`../components/search/...` should be `../components/features/search/...`)
- wrong argument count and wrong props in `ContractIntelligence.tsx:104,362`
- a type mismatch in `SearchPage.tsx:40`
- a `never` type error in `message.tsx:31`

On top of the build failure:
- `enhancedSearchApi.ts:72,89` call `/documents/enhanced/...` without the `/api` prefix, so those requests 404.
- The API base URL is hardcoded to `http://localhost:8000`.
- The frontend Docker image only runs the Vite dev server, so the build is never exercised.

**N20. `backend/dependencies.py` imports modules that don't exist**
It imports `backend.services.*` and `backend.agent_manager`, so the module can never be imported.

### 🟠 Security

**S1. The LLM decides the tenant in chat search**
`shared/utils/contract_search_tool.py:218`, `enhanced_contract_search_tool.py:392`
`tenant_id` is a tool argument the model fills in. A user can type "search tenant X's contracts" and read another tenant's data. The model also has to *guess* the tenant, so uploaded contracts (stored under `default-tenant`) are often never found.

**S2. Cypher injection through the LLM**
`contract_search_tool.py:168-169`
`cypher_aggregation` is raw Cypher written by the LLM and appended straight onto the query. A prompt injection can run arbitrary reads or writes (for example `DETACH DELETE`) and skip the tenant filter. The prompt guard that should screen this is broken (C6, N1 and N2).

**S3. RBAC trusts a client-supplied header, and the UI depends on the ADMIN default**
- Anyone can send `X-User-Role: ADMIN`.
- The frontend **never sends a role header**, so the whole UI only works because of the `ADMIN` default. Changing the default alone will break the UI.
- `run()` never passes `user_role` to `runner`, so audit logs always record `unknown`.

**S4. `tenant_id` is a free query parameter on every endpoint**
It isn't tied to any identity, and the frontend never sends it, so all data lives in `default-tenant`.

**S5. Endpoints with no auth or tenant checks**
- `/api/intelligence/contracts/{id}/status`
- `/api/documents/enhanced/embedding-status/{id}`
- `/api/policies/applicable/...`
- `/api/supervisor/workflow/{id}/status`

`/api/documents/debug/contracts` (in `document_upload.py`) is mounted **even in production** and lists every tenant's contracts.

**S6. The graph is shared across tenants**
`contract_repository.py:156,175`
- `Party` and `Country` nodes are MERGEd globally by name.
- `Section` and `Clause` nodes are MERGEd by IDs derived from the contract, with no tenant in the ID.
- Policy `GET` and `DELETE /{policy_id}` don't check the tenant (an IDOR).

**S7. Whole contract text ends up in audit logs**
`governance/base.py:92-97`
Guard violations copy `context_metadata` into the audit record, including `source_text`, which holds the full tool output.

**S8. Deliberate 400 and 404 responses become 500s**
Handlers raise `HTTPException(400/404)` inside `try: ... except Exception`, which converts them into 500s (`policy_api.py`; `404 → 500` [verified]).

### 🟡 Reliability and performance

**R1. Analysis freezes the whole server**
`contract_intelligence_agents.py:386-388`
The intelligence analysis runs synchronously inside an `async` route, and `future.result()` blocks the event loop, so **every user's request stalls** until it finishes. The same thing happens with:
- the sync `model.invoke` calls in the guards
- the supervisor's `time.sleep` retries
- the sync Neo4j calls inside `async def store_contract`

**R2. `workflow_tracker` is shared global state**
It's written from worker threads and concurrent requests. The planning path calls `complete_workflow()` without ever calling `start_workflow()`.

**R3. Import-time side effects**
`Neo4jGraph` (`contract_search_tool.py:53`) and `GeminiEmbeddingService` (`gemini_embedding_service.py:77`) are built at import time. The app and the tests can't even be imported without a Neo4j URI and a `GOOGLE_API_KEY`.

**R4. Cache and metrics don't do what they claim**
- The in-memory cache ignores TTLs and grows without limit.
- `CACHE_ENABLED` is ignored.
- `@track_performance` wraps async functions in a sync wrapper, so `batch_processing` is timed at about 0 ms.

**R5. Model configuration is broken**
- `claude-3-5-sonnet-latest` and `gemini-1.5-pro` are retired models.
- `/models` offers `gemini-2.5-pro` and `mistral-large`, but `_get_llm_for_model` in the upload services rejects them.
- `LLMManager.agents` is a class-level dict shared by every instance.

**R6. Duplicate key in a Cypher map**
`contract_repository.py:87,96`: `tenant_id` appears twice in the `CREATE` map.

**R7. Docker setup is not production-ready**
- The backend container runs `fastapi dev` (reload mode).
- `docker-compose.yml` has no Neo4j or Redis service.
- It falls back to the read-only `demo.neo4jlabs.com` credentials, so every write fails.

**R8. The default tenant has three different names**
`"default-tenant"`, `"demo_tenant_1"` (`AuditLogger`, `ChunkStorageService`, the precedent tool) and `"default"` (CoT).

### 🔵 Logic and quality

- **L1.** The IP check uses the substring `"ip"`, so it also matches "Shipping", "Relationship", "Equipment" and "Membership". Those get false CRITICAL IP violations and redlines (`intelligence_tools.py:223,360`).
- **L2.** CoT and `PolicyComplianceAgent` read `clause['type']`, but clauses use `clause_type`, so every clause is `unknown`/`general` (`chain_of_thought_agent.py:59,81`, `policy_agents.py` in `_check_clause_compliance`).
- **L3.** ReACT never calls an LLM. It runs the same hardcoded detector 3 times, its confidence never reaches 0.8, and it reasons about an `original_query` that is never set.
- **L4.** `IntelligenceState` has no `validation_result` key, so LangGraph drops it, and the stored `validation_score` is always 0.
- **L5.** Because `ClauseDetectorTool` returns hardcoded clauses, **every contract gets the same result**: 1 HIGH violation ("$50,000" liability), 1 CRITICAL redline, and risk 45 (MEDIUM).
- **L6.** Each upload is audited twice (once by the decorator, once manually). The `audit_log` decorator also has an operator-precedence bug when it builds `resource_id`.
- **L7.** The risk score starts at 30 even when no clauses are found.

### Tests

The 8 governance unit tests pass (`test_rbac_unit.py`, `test_pii_unit.py`), but none of them cover the broken paths above. Most tests under `tests/` need live Neo4j and Gemini.

---

## Totals

| Severity | First report | This pass (new) |
|---|---|---|
| 🔴 Critical / broken | 7 crash-level + others | 20 (N1–N20) |
| 🟠 Security | 3 | 8 (S1–S8) |
| 🟡 Reliability | several | 8 (R1–R8) |
| 🔵 Logic | several | 7 (L1–L7) |

6 items from the first report are corrected (C1–C6).

## Suggested fix order

1. **Make chat work.** Fix `injection.py:21` (`prompt` → `input_text`) and `intent.py:51` (`except Exception as e`). Give the guards a raw chat model instead of the agent graph (N1). Import `AuditEventType` in `main.py`.
2. **Close the tenant and Cypher holes.** Inject `tenant_id` from the server, not from the LLM (S1). Remove or allow-list `cypher_aggregation` (S2).
3. **Make analysis real.** Wire an actual LLM into `ClauseDetectorTool` and the orchestrator (N5, L5). Stop persisting failed runs (N7). Move blocking work off the event loop (R1).
4. **Fix the upload paths:** N13, N14 and N15, plus the enhanced-upload `ainvoke` (C2).
5. **Fix policies, patterns, supervisor and MCP:** N9–N12, N17 and N18.
6. **Fix the frontend build** (N19), then replace header-based RBAC with real authentication (S3 and S4).
