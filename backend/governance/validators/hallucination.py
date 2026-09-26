from typing import Dict, Any, Optional
from ..base import IGuardValidator, GuardResult
from ..llm_judge import ask_json, guard_fail_closed
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

class HallucinationValidator(IGuardValidator):
    """
    Detects and flags factually incorrect or unsupported AI-generated content.
    Uses an LLM-based "Critic" to compare the output against provided source context.
    """
    
    MAX_SOURCE_CHARS = 30000

    def __init__(self, llm=None):
        super().__init__()
        self.llm = llm

    def validate(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> GuardResult:
        """
        Validate if the AI generated output is supported by the source context.
        """
        if not context or 'source_text' not in context:
            logger.warning("Hallucination check skipped: No source context ('source_text') provided in metadata.")
            return GuardResult(is_safe=True)

        source_text = context.get('source_text', '')
        if not source_text:
            return GuardResult(is_safe=True)

        logger.info("Performing hallucination check against source context...")

        system_instruction = (
            "You are a Fact-Checking Auditor for a Contract Analysis system. "
            "Your task is to determine if the AI-generated 'Response' is strictly "
            "supported by the provided 'Source Text' (the contract).\n\n"
            "Guidelines:\n"
            "1. Flag as hallucination if the Response mentions numbers, dates, or parties "
            "not present in the Source Text.\n"
            "2. Flag as hallucination if the Response makes legal claims or "
            "interpretations that contradict the Source Text.\n"
            "3. If the Response says 'I don't know' or 'The contract does not specify', "
            "that is NOT a hallucination.\n\n"
            "Respond ONLY with a JSON object: {\"is_hallucination\": boolean, \"reason\": \"string\", \"confidence\": float}"
        )

        prompt = (
            f"Source Text (Contract Content):\n{source_text[:self.MAX_SOURCE_CHARS]}\n\n"
            f"AI-Generated Response to Verify:\n{input_text}\n"
        )

        try:
            data = ask_json(system_instruction, prompt, llm=self.llm)
        except Exception as e:
            logger.error(f"Hallucination check failed: {e}")
            if guard_fail_closed():
                return GuardResult(is_safe=False, violation_type="GUARD_UNAVAILABLE",
                                   message="Fact-check unavailable.")
            return GuardResult(is_safe=True, metadata={"guard_error": str(e)})

        if data.get("is_hallucination", False):
            logger.warning(f"Hallucination detected: {data.get('reason')}")
            return GuardResult(
                is_safe=False,
                violation_type="HALLUCINATION_DETECTED",
                message=f"The assistant's response contains information not supported by the source contract: {data.get('reason')}",
                metadata={"hallucination_details": data}
            )
        return GuardResult(is_safe=True)
