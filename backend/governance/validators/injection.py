import re
from typing import Optional, Dict, Any
from ..base import IGuardValidator, GuardResult


class InjectionValidator(IGuardValidator):
    """Detects prompt injection and jailbreak attempts"""

    PATTERNS = [
        r"(?i)ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+instructions",
        r"(?i)system\s+override",
        r"(?i)you\s+are\s+now\s+a\s+DAN",
        r"(?i)\bjailbreak\b",
        r"(?i)forget\s+everything",
        r"(?i)disregard\s+(all\s+)?(prior|previous)\s+(rules|instructions)",
        r"(?i)(output|print|show|reveal)\s+(the\s+|your\s+)?system\s+prompt",
        r"(?i)reveal\s+your\s+instructions",
        # Attempts to smuggle database commands through the search tool
        r"(?i)\b(detach\s+delete|drop\s+(index|constraint|database)|call\s+(dbms|apoc)\.)",
    ]

    def validate(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> GuardResult:
        for pattern in self.PATTERNS:
            if re.search(pattern, input_text):
                return GuardResult(
                    is_safe=False,
                    violation_type="PROMPT_INJECTION",
                    message="Potential prompt injection attempt detected.",
                    metadata={"pattern_matched": pattern}
                )
        return GuardResult(is_safe=True)
