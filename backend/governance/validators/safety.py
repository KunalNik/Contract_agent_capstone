from typing import Optional, Dict, Any
from ..base import IGuardValidator, GuardResult
from ..llm_judge import ask_json, guard_fail_closed
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

class LlamaGuardValidator(IGuardValidator):
    """
    Llama-Guard-style output safety check.

    Uses the configured chat model (GUARD_MODEL, Gemini by default) prompted
    with the Llama Guard 3 hazard taxonomy; it does not call a Llama Guard model.
    """
    RISK_CATEGORIES = {
        "S1": "Violent Crimes",
        "S2": "Non-Violent Crimes",
        "S3": "Sexually Explicit Content",
        "S4": "Child Sexual Exploitation",
        "S5": "Defamation",
        "S6": "Specialized Advice",
        "S7": "Privacy",
        "S8": "Intellectual Property",
        "S9": "Hate Speech",
        "S10": "Harassment",
        "S11": "Election Integrity",
        "S12": "Criminal Planning"
    }

    def __init__(self, llm=None):
        super().__init__()
        self.llm = llm

    def validate(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> GuardResult:
        system_instruction = (
            "You are a Llama Guard safety classifier. Analyze the provided AI response "
            "and determine if it violates any of the following safety categories:\n"
            + "\n".join([f"{k}: {v}" for k, v in self.RISK_CATEGORIES.items()]) + "\n"
            "This assistant's purpose is explaining and summarising business contracts; describing "
            "contract terms, risks, obligations or suggested redlines is expected and is NOT S6 "
            "(Specialized Advice) or S8 (Intellectual Property). Only flag clear violations.\n"
            "Respond ONLY with a JSON object: {\"is_safe\": boolean, \"violation_category\": \"code or null\", \"reason\": \"string\"}"
        )
        
        try:
            data = ask_json(system_instruction, f"AI Output: {input_text}", llm=self.llm)
        except Exception as e:
            logger.error(f"Llama Guard validation failed: {e}")
            if guard_fail_closed():
                return GuardResult(is_safe=False, violation_type="GUARD_UNAVAILABLE",
                                   message="Output safety check unavailable.")
            return GuardResult(is_safe=True, metadata={"guard_error": str(e)})

        if not data.get("is_safe", True):
            category = data.get("violation_category") or "UNKNOWN"
            category_name = self.RISK_CATEGORIES.get(category, "General Safety Violation")
            return GuardResult(
                is_safe=False,
                violation_type="UNSAFE_OUTPUT",
                message=f"Output flagged for {category_name}: {data.get('reason')}",
                metadata={"category": category}
            )
        return GuardResult(is_safe=True)
