from typing import Dict, Any

from .base_adapter import BaseAgentAdapter, AgentConfig
from .interfaces import AgentContext, AgentResult
from ...llm_manager import LLMManager
from backend.shared.utils.async_utils import run_coro_sync
from backend.shared.utils.request_context import DEFAULT_TENANT

# Agent ids as registered by AgentFactory (the adapters used to look up
# "pdf-processing"/"clause-extraction" and never found earlier results).
PDF_AGENT = "pdf_processing"
CLAUSE_AGENT = "clause_extraction"
RISK_AGENT = "risk_assessment"


def _workflow_input(context: AgentContext) -> Dict[str, Any]:
    wf = context.workflow_context
    shared = wf.get_shared_data("input_data", {}) if wf is not None and hasattr(wf, "get_shared_data") else {}
    return {**(shared or {}), **(context.input_data or {})}


def _analyse_once(context: AgentContext, llm_manager: LLMManager, contract_id: str, tenant_id: str):
    """Run the intelligence pipeline once per workflow and share the result.

    Clause extraction and risk assessment both need it; running it twice
    doubled the cost and latency of every workflow.
    """
    wf = context.workflow_context
    cached = wf.get_shared_data("intelligence") if wf is not None else None
    if cached is not None:
        return cached
    from ...application.services.contract_intelligence_service import ContractIntelligenceServiceFactory
    service = ContractIntelligenceServiceFactory.create_service(llm_manager)
    intelligence = run_coro_sync(service.analyze_contract_by_id(contract_id, tenant_id, "gemini-2.5-flash"))
    if wf is not None:
        wf.set_shared_data("intelligence", intelligence)
    return intelligence


class PDFProcessingAdapter(BaseAgentAdapter):
    def __init__(self, config: AgentConfig, llm_manager: LLMManager):
        super().__init__(config)
        self.llm_manager = llm_manager
        
    def prepare_input(self, context: AgentContext) -> Dict[str, Any]:
        data = _workflow_input(context)
        return {
            "file_path": data.get("file_path"),
            "filename": data.get("filename", ""),
            "contract_id": data.get("contract_id"),
            "tenant_id": data.get("tenant_id", DEFAULT_TENANT)
        }
    
    def call_agent(self, input_data: Dict[str, Any]) -> Any:
        if not input_data.get("file_path"):
            # Workflow started from an existing contract: nothing to ingest
            if input_data.get("contract_id"):
                return {"status": "success", "contract_id": input_data["contract_id"],
                        "final_result": "Using existing contract"}
            return {"status": "error", "final_result": "Workflow input needs file_path or contract_id"}

        from ...application.services.document_processing_service import DocumentServiceFactory
        from ...domain.entities import DocumentProcessingRequest
        service = DocumentServiceFactory.create_service(self.llm_manager)
        request = DocumentProcessingRequest(
            file_path=input_data["file_path"],
            filename=input_data["filename"],
            tenant_id=input_data.get("tenant_id", DEFAULT_TENANT),
            processing_options={"model": "gemini-2.5-flash"}
        )
        # process_pdf_upload is async; it used to be returned un-awaited
        return run_coro_sync(service.process_pdf_upload(request))
    
    def format_output(self, raw_result: Any) -> AgentResult:
        return AgentResult(
            status="success" if raw_result.get("contract_id") else "error",
            data={
                "text_content": raw_result.get("final_result", ""),
                "contract_id": raw_result.get("contract_id"),
                "metadata": {"processing_complete": bool(raw_result.get("contract_id"))}
            },
            confidence=0.8 if raw_result.get("contract_id") else 0.0
        )


class ClauseExtractionAdapter(BaseAgentAdapter):
    def __init__(self, config: AgentConfig, llm_manager: LLMManager):
        super().__init__(config)
        self.llm_manager = llm_manager
        self._context = None

    def prepare_input(self, context: AgentContext) -> Dict[str, Any]:
        self._context = context
        data = _workflow_input(context)
        pdf_result = context.workflow_context.get_agent_result(PDF_AGENT) if context.workflow_context else None
        return {
            "contract_id": (pdf_result.data.get("contract_id") if pdf_result else None) or data.get("contract_id"),
            "tenant_id": data.get("tenant_id", DEFAULT_TENANT),
        }
    
    def call_agent(self, input_data: Dict[str, Any]) -> Any:
        if not input_data["contract_id"]:
            return None
        return _analyse_once(self._context, self.llm_manager, input_data["contract_id"], input_data["tenant_id"])
    
    def format_output(self, raw_result: Any) -> AgentResult:
        if raw_result is None or getattr(raw_result, "status", "failed") == "failed":
            return AgentResult(status="error",
                               data={"clauses": [], "error": getattr(raw_result, "error", None) or "No contract to analyse"},
                               confidence=0.0)
        clauses_data = [
            {"clause_type": c.clause_type, "content": c.content, "confidence_score": c.confidence_score}
            for c in raw_result.clauses
        ]
        confidence = sum(c["confidence_score"] for c in clauses_data) / len(clauses_data) if clauses_data else 0.0
        return AgentResult(status="success", data={"clauses": clauses_data}, confidence=confidence)


class RiskAssessmentAdapter(BaseAgentAdapter):
    def __init__(self, config: AgentConfig, llm_manager: LLMManager):
        super().__init__(config)
        self.llm_manager = llm_manager
        self._context = None

    def prepare_input(self, context: AgentContext) -> Dict[str, Any]:
        self._context = context
        data = _workflow_input(context)
        pdf_result = context.workflow_context.get_agent_result(PDF_AGENT) if context.workflow_context else None
        return {
            "contract_id": (pdf_result.data.get("contract_id") if pdf_result else None) or data.get("contract_id"),
            "tenant_id": data.get("tenant_id", DEFAULT_TENANT),
        }
    
    def call_agent(self, input_data: Dict[str, Any]) -> Any:
        if not input_data["contract_id"]:
            return None
        return _analyse_once(self._context, self.llm_manager, input_data["contract_id"], input_data["tenant_id"])
    
    def format_output(self, raw_result: Any) -> AgentResult:
        if raw_result is None or getattr(raw_result, "status", "failed") == "failed":
            # Previously a made-up MEDIUM/50 risk was reported as success here
            return AgentResult(status="error",
                               data={"error": getattr(raw_result, "error", None) or "No contract to assess"},
                               confidence=0.0)
        risk = raw_result.risk_assessment
        return AgentResult(
            status="success",
            data={
                "risk_score": risk.overall_risk_score,
                "risk_level": risk.risk_level,
                "critical_issues": risk.critical_issues,
                "recommendations": risk.recommendations
            },
            confidence=0.8
        )
