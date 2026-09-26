import re
from typing import Optional, Dict, Any
from ..base import IGuardValidator, GuardResult


class TopicValidator(IGuardValidator):
    """Blocks requests that are clearly unrelated to contract analysis.

    Only explicit off-topic tasks are blocked. Prompts that merely lack a
    contract keyword are allowed through (the LLM intent check and the
    assistant's system prompt handle borderline cases); the old
    "no keyword => block" rule rejected ordinary questions such as
    "What are the payment terms?".
    """

    OFF_TOPIC_PATTERNS = [
        r"\btell me a joke\b",
        r"\bwrite (me )?a (poem|song|story)\b",
        r"\bhow (to|do i|can i) make a (bomb|weapon|explosive)\b",
        r"\b(write|give me) (python|javascript|java|c\+\+|sql) code\b",
        r"\bpython code for\b",
        r"\bhow do i cook\b",
        r"\brecipe for\b",
        r"\bweather (in|for|today)\b",
        r"\bwho is the president\b",
    ]

    def validate(self, input_text: str, context: Optional[Dict[str, Any]] = None) -> GuardResult:
        prompt_lower = input_text.lower()
        for pattern in self.OFF_TOPIC_PATTERNS:
            if re.search(pattern, prompt_lower):
                return GuardResult(
                    is_safe=False,
                    violation_type="OUT_OF_SCOPE",
                    message="Request is outside the scope of contract analysis."
                )
        return GuardResult(is_safe=True)
