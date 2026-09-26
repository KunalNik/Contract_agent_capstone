import asyncio
import json
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, AIMessageChunk
from backend.llm_manager import LLMManager, set_shared_llm_manager
from backend.api.document_upload import router as document_router
from backend.api.contract_intelligence import router as intelligence_router
from backend.api.routes.debug import create_debug_router
from backend.api.routes.production import create_production_router
from backend.shared.utils.route_utils import is_development, conditionally_include_router
from backend.api.enhanced_contract_search import router as enhanced_search_router
from backend.api.enhanced_document_upload import router as enhanced_upload_router
from backend.agents.agent_workflow_tracker import get_current_workflow_status
from backend.shared.middleware.tracing import TracingMiddleware
from backend.shared.utils.logger import get_logger, correlation_id_var
from backend.governance.prompt_guard import PromptGuard
from backend.governance.output_guard import OutputGuard
from backend.governance.rbac import Permission, requires_permission, get_current_user, CurrentUser
from backend.governance.pii_engine import PIIEngine
from backend.infrastructure.audit_logger import AuditLogger, AuditEventType
from backend.shared.utils.request_context import tenant_id_var, user_role_var

logger = get_logger(__name__)

import os
from openinference.instrumentation.langchain import LangChainInstrumentor

load_dotenv()

# Initialize Phoenix tracing (OpenTelemetry) only when a collector is configured;
# otherwise the exporter retries forever against localhost and floods the logs.
phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
if phoenix_endpoint and os.environ.get("TRACING_ENABLED", "true").lower() not in ("0", "false", "no"):
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=phoenix_endpoint)))
        LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
    except Exception as e:
        logger.warning(f"Failed to initialize OpenTelemetry tracing: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - build models once and share them with guards and agents
    app.state.llm_manager = LLMManager()
    set_shared_llm_manager(app.state.llm_manager)
    yield
    # Shutdown - cleanup if needed

app = FastAPI(lifespan=lifespan)

# Dependency injection
def get_llm_manager(request: Request):
    return request.app.state.llm_manager


app.add_middleware(TracingMiddleware)

# CORS: explicit origins from CORS_ORIGINS (comma separated). A wildcard origin
# is only allowed without credentials, per the CORS spec.
_cors_origins = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials="*" not in _cors_origins,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers based on environment
app.include_router(document_router)
app.include_router(intelligence_router)
app.include_router(enhanced_search_router, prefix="/api")
app.include_router(enhanced_upload_router)

# Supervisor API
from backend.api.supervisor_api import router as supervisor_router
app.include_router(supervisor_router)

# Feedback API (Phase 2)
from backend.api.feedback_api import router as feedback_router
app.include_router(feedback_router)

# Monitoring API (Phase 3)
from backend.api.monitoring_api import router as monitoring_router
app.include_router(monitoring_router)

# Audit API (Production)
from backend.api.audit_api import router as audit_router
app.include_router(audit_router)

# AI Patterns API
from backend.api.patterns_api import router as patterns_router
app.include_router(patterns_router)

# Policy Management API
from backend.api.policy_api import router as policy_router
app.include_router(policy_router)

# Debug routes (development only)
debug_router = create_debug_router()
conditionally_include_router(app, debug_router, is_development())

@app.get("/api/workflow/status", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_workflow_status():
    """Get current multi-agent workflow status for executive dashboard"""
    return get_current_workflow_status()

@app.get("/api/planning/status", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_planning_status():
    """Get autonomous planning agent status"""
    from backend.agents.planning.planning_agent import PlanningAgent

    return {
        "agent_type": "Autonomous Planning & Reasoning Agent",
        "capabilities": [
            "Query Analysis & Decomposition",
            "Execution Plan Generation", 
            "Self-Reflection & Validation",
            "Adaptive Strategy Selection",
            "Performance Learning"
        ],
        "available_strategies": ["simple", "complex", "risk_focused", "compliance_focused"],
        "execution_history_count": PlanningAgent.total_plans_created
    }


@app.get("/")
async def root():
    return {"status": "OK"}


@app.get("/api/health")
async def health(request: Request):
    """Readiness: reports database and LLM availability without failing startup."""
    from backend.shared.utils.contract_search_tool import graph
    db_ok, db_error = True, None
    try:
        graph.query("RETURN 1 AS ok")
    except Exception as e:
        db_ok, db_error = False, str(e)[:200]
    models = request.app.state.llm_manager.available_models()
    healthy = db_ok and bool(models)
    return {
        "status": "healthy" if healthy else "degraded",
        "database": {"ok": db_ok, "error": db_error},
        "llm": {"ok": bool(models), "models": models},
    }


class RunPayload(BaseModel):
    model: str
    prompt: str
    history: str

def rebuild_history(history):
    history = json.loads(history)

    type_to_class = {
        "human": HumanMessage,
        "tool": ToolMessage,
        "ai": AIMessage
    }

    messages = []
    for item_json_str in history:
        item = json.loads(item_json_str)
        item_class = type_to_class.get(item.get("type"))
        if item_class:
            # use pydantic BaseClass method to rebuild message model from json string dumped by model_dump_json
            messages.append(item_class.model_validate_json(item_json_str))

    return messages


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class _PIIStreamRedactor:
    """Redacts PII from streamed text before it reaches the client.

    Text is held back until a safe boundary (newline or end of sentence), so a
    phone number or email split across two chunks is still caught.
    """
    FLUSH_LIMIT = 400

    def __init__(self):
        self.buffer = ""

    def feed(self, text: str) -> str:
        self.buffer += text
        cut = max(self.buffer.rfind("\n"), self.buffer.rfind(". "), self.buffer.rfind("? "), self.buffer.rfind("! "))
        if cut == -1 and len(self.buffer) < self.FLUSH_LIMIT:
            return ""
        if cut == -1:
            cut = self.buffer.rfind(" ", 0, len(self.buffer) - 40)
            if cut == -1:
                return ""
        ready, self.buffer = self.buffer[:cut + 1], self.buffer[cut + 1:]
        return PIIEngine.redact(ready)

    def flush(self) -> str:
        ready, self.buffer = self.buffer, ""
        return PIIEngine.redact(ready) if ready else ""


def _chunk_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
    return str(content or "")


async def runner(model: str, prompt: str, history: str, llm_mgr: LLMManager,
                 user_role: str = "unknown", tenant_id: str = "default-tenant", user_id: str = "user"):
    """Stream a chat turn as SSE. Always ends with an 'end' event, even on failure."""
    tenant_id_var.set(tenant_id)
    user_role_var.set(user_role)
    try:
        async for event in _run_chat(model, prompt, history, llm_mgr, user_role, tenant_id, user_id):
            yield event
    except Exception as e:
        logger.error(f"Chat run failed: {e}", exc_info=True)
        yield _sse({'content': f'The assistant could not complete this request: {e}', 'type': 'error'})
    yield _sse({'content': '', 'type': 'end'})


async def _run_chat(model: str, prompt: str, history: str, llm_mgr: LLMManager,
                    user_role: str, tenant_id: str, user_id: str):
    logger.info(f"Processing LLM request for model '{model}' for user_role '{user_role}'")

    # Initialize AuditLogger and AgentAuditService for Guard persistence
    from backend.infrastructure.agent_audit_service import AgentAuditService

    audit_logger = AuditLogger()
    agent_audit = AgentAuditService(audit_logger)
    session_id = correlation_id_var.get() or "unknown_session"
    context_metadata = {"user_role": user_role, "tenant_id": tenant_id}

    # 0. Log User Interaction
    agent_audit.log_user_interaction(user_id=user_id, prompt=prompt, session_id=session_id)

    # Resolve the model up front so an unknown model is a clean error, not a crash
    agent = llm_mgr.get_model_by_name(model)

    # 1. Prompt Guard Pre-Check (sync LLM call -> worker thread, keeps the event loop free)
    guard = PromptGuard(audit_logger=audit_logger)
    guard_result = await asyncio.to_thread(guard.validate, prompt, context_metadata)

    agent_audit.log_guard_check(
        guard_name="Prompt Guard",
        is_safe=guard_result.is_safe,
        violation_type=guard_result.violation_type,
        session_id=session_id
    )

    if not guard_result.is_safe:
        logger.error(f"Prompt blocked by Guard: {guard_result.violation_type}")
        yield _sse({'content': guard_result.message, 'type': 'error'})
        return

    # history comes in from FE as stringified list of dumped model messages
    previous_messages = rebuild_history(history) if history and history != "[]" else []

    prompt_message = HumanMessage(content=prompt)
    input_messages = [*previous_messages, prompt_message]

    corr_id = correlation_id_var.get()
    run_tags = [f"correlation_id:{corr_id}"] if corr_id else []

    messages = agent.astream(
        input={"messages": input_messages},
        config={"tags": run_tags},
        stream_mode=["messages", "updates"]
    )

    # Context management: the 'history' event carries the FULL conversation,
    # so the client must replace (not append to) its stored history.
    context = json.loads(history) if history else []
    context.append(prompt_message.model_dump_json())
    turn_start = len(context)  # messages after this index belong to this turn

    ai_full_content = ""
    redactor = _PIIStreamRedactor()

    async for message in messages:
        if message[0] == "messages":
            chunk = message[1][0]

            # output tool call section type
            if getattr(chunk, "tool_calls", None):
                for tool in chunk.tool_calls:
                    if tool.get('name'):
                        yield _sse({'content': json.dumps(tool), 'type': 'tool_call'})

            if isinstance(chunk, ToolMessage):
                yield _sse({'content': PIIEngine.redact(_chunk_text(chunk.content)), 'type': 'tool_message'})
            elif isinstance(chunk, AIMessage):  # AIMessageChunk (streaming) or AIMessage (non-streaming models)
                text = _chunk_text(chunk.content)
                ai_full_content += text
                safe = redactor.feed(text)
                if safe:
                    yield _sse({'content': safe, 'type': 'ai_message'})

        elif message[0] == "updates":
            # use pydantic BaseClass method model_dump_json to dump message model to be stringified into history
            update = message[1] or {}
            if "assistant" in update:
                for history_message in update["assistant"]["messages"]:
                    context.append(history_message.model_dump_json())
            elif "tools" in update:
                for tool_message in update["tools"]["messages"]:
                    if hasattr(tool_message, 'model_dump_json'):
                        context.append(tool_message.model_dump_json())

    tail = redactor.flush()
    if tail:
        yield _sse({'content': tail, 'type': 'ai_message'})

    # 2. Output Guard Post-Check
    # Extract source context from tool results for hallucination check
    tool_contents = []
    for msg_str in context:
        try:
            msg = json.loads(msg_str)
            if msg.get("type") == "tool":
                tool_contents.append(_chunk_text(msg.get("content", "")))
        except Exception:
            pass

    if tool_contents:
        context_metadata["source_text"] = "\n---\n".join(tool_contents)

    output_guard = OutputGuard(audit_logger=audit_logger)
    post_check_result = await asyncio.to_thread(output_guard.validate, ai_full_content, context_metadata)

    agent_audit.log_guard_check(
        guard_name="Output Guard",
        is_safe=post_check_result.is_safe,
        violation_type=post_check_result.violation_type,
        session_id=session_id
    )

    if not post_check_result.is_safe:
        logger.error(f"Output blocked by Output Guard: {post_check_result.violation_type}")
        # Tell the client to remove what was already shown, then explain why
        yield _sse({'content': '', 'type': 'retract'})
        yield _sse({'content': '[CONTENT REMOVED DUE TO SAFETY POLICY] ' + (post_check_result.message or ''), 'type': 'error'})
        # Keep the blocked answer (and its tool calls) out of the conversation history
        context = context[:turn_start]
    else:
        redacted_content = post_check_result.metadata.get("redacted_content")
        if redacted_content and redacted_content != ai_full_content:
            logger.info("PII redaction applied to AI output")
            audit_logger.log_event(
                event_type=AuditEventType.SECURITY_VIOLATION,
                resource_id=session_id,
                action="pii_redaction",
                tenant_id=tenant_id,
                metadata={"status": "redacted"}
            )
            # Store the redacted version of the final answer in history
            for i in range(len(context) - 1, -1, -1):
                msg_data = json.loads(context[i])
                if msg_data.get("type") == "ai":
                    msg_data["content"] = redacted_content
                    context[i] = json.dumps(msg_data)
                    break

    yield _sse({'content': context, 'type': 'history'})


@app.post("/api/run/", dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def run(
    payload: RunPayload,
    llm_mgr: LLMManager = Depends(get_llm_manager),
    user: CurrentUser = Depends(get_current_user),
):
    return StreamingResponse(
        runner(
            model=payload.model,
            prompt=payload.prompt,
            history=payload.history,
            llm_mgr=llm_mgr,
            user_role=user.role.value,
            tenant_id=user.tenant_id,
            user_id=user.user_id,
        ),
        media_type="text/event-stream",
    )
